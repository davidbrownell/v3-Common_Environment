# ----------------------------------------------------------------------
# |  
# |  AcquireBinaries.py
# |  
# |  David Brownell <db@DavidBrownell.com>
# |      2018-09-11 07:38:33
# |  
# ----------------------------------------------------------------------
# |  
# |  Copyright David Brownell 2018-19.
# |  Distributed under the Boost Software License, Version 1.0.
# |  (See accompanying file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
# |  
# ----------------------------------------------------------------------
"""Methods that help during setup and activate to acquire/download/unzip/install binaries."""

import json
import os
import shutil
import sys
import textwrap

import inflect as inflect_mod
import six
import tqdm

import CommonEnvironment
from CommonEnvironment import Nonlocals
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import CommandLine
from CommonEnvironment import FileSystem
from CommonEnvironment import Process
from CommonEnvironment.Shell.All import CurrentShell
from CommonEnvironment.StreamDecorator import StreamDecorator
from CommonEnvironment import StringHelpers
from CommonEnvironment import TaskPool

# ----------------------------------------------------------------------
_script_fullpath = CommonEnvironment.ThisFullpath()
_script_dir, _script_name = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

inflect                                     = inflect_mod.engine()

# ----------------------------------------------------------------------
@CommandLine.EntryPoint
@CommandLine.Constraints( name=CommandLine.StringTypeInfo(),
                          uri=CommandLine.UriTypeInfo(),
                          output_dir=CommandLine.DirectoryTypeInfo(ensure_exists=False),
                          unique_id=CommandLine.StringTypeInfo(arity='?'),
                          output_stream=None,
                        )
def Install( name,
             uri,
             output_dir,
             unique_id=None,
             output_stream=sys.stdout,
           ):
    """Installs binaries to the specified output directory"""

    output_stream.write("Processing '{}'...".format(name))
    with StreamDecorator(output_stream).DoneManager( suffix='\n',
                                                   ) as dm:
        if not _PreviousInstallation.Exists(output_dir):
            prev_installation = None
        else:
            try:
                prev_installation = _PreviousInstallation.Load(output_dir)
            except Exception as ex:
                dm.stream.write("WARNING: {}\n".format(StringHelpers.LeftJustify( str(ex),
                                                                                  len("WARNING: "),
                                                                                )))
                dm.result = 1

                prev_installation = None

        if prev_installation is not None:
            if prev_installation.UniqueId == unique_id:
                dm.stream.write(textwrap.dedent(
                    """\
                    The content already exists and will not be overwritten. Please delete the directory 
                    if this content is not valid or needs to be reacquired.

                        {}
                    """).format(output_dir))

                return dm.result

            dm.result = _CleanImpl( output_dir,
                                    prev_installation.OriginalFileNames, 
                                    dm.stream,
                                  )
            if dm.result < 0:
                return dm.result

        if uri.Scheme == "file":
            filename = uri.ToFilename()
            FilenameCleanup = lambda: None

        else:
            uri = uri.ToString()

            with dm.stream.SingleLineDoneManager("Downloading '{}'...".format(uri)) as download_dm:
                nonlocals = Nonlocals( progress_bar=None,
                                       current=0,
                                     )

                # ----------------------------------------------------------------------
                def Callback(count, block_size, total_size):
                    if nonlocals.progress_bar is None:
                        nonlocals.progress_bar = tqdm.tqdm( total=total_size,
                                                            desc="Downloading",
                                                            unit=" bytes",
                                                            file=download_dm.stream,
                                                            mininterval=0.5,
                                                            leave=False,
                                                            ncols=120,
                                                          )
                    else:
                        assert count, block_size

                        current = min(count * block_size, total_size)
                        assert current >= nonlocals.current 

                        nonlocals.progress_bar.update(current - nonlocals.current)
                        nonlocals.current = current

                # ----------------------------------------------------------------------

                filename = CurrentShell.CreateTempFilename(".zip")
                FilenameCleanup = lambda: FileSystem.RemoveFile(filename)

                download_dm.result = six.moves.urllib.request.urlretrieve( uri, 
                                                                           filename, 
                                                                           reporthook=Callback,
                                                                         )
                if nonlocals.progress_bar is not None:
                    nonlocals.progress_bar.close()

                if download_dm.result != 0:
                    return download_dm.result

        with CallOnExit(FilenameCleanup):
            assert os.path.isfile(filename), filename
            temp_directory = CurrentShell.CreateTempDirectory()

            # Extract the content to a temporary folder
            dm.stream.write("Extracting content...")
            with dm.stream.DoneManager() as extract_dm:
                command_line = '7za x -y "{input}"' \
                                    .format( input=filename,
                                           )

                sink = six.moves.StringIO()
                
                previous_dir = os.getcwd()
                os.chdir(temp_directory)

                with CallOnExit(lambda: os.chdir(previous_dir)):
                    extract_dm.result = Process.Execute(command_line, sink)
                    if extract_dm.result != 0:
                        extract_dm.stream.write(sink.getvalue())
                        return extract_dm.result

            with CallOnExit(lambda: FileSystem.RemoveTree(temp_directory)):
                # Get a list of the original items
                FileSystem.MakeDirs(output_dir)
                original_items = list(os.listdir(output_dir))

                # Write the metadata
                _PreviousInstallation( unique_id,
                                       original_items,
                                     ).Save(temp_directory)

                # Move items
                dm.stream.write("Finalizing content...")
                with dm.stream.DoneManager() as final_dm:
                    for item in os.listdir(temp_directory):
                        src = os.path.join(temp_directory, item)
                        dst = os.path.join(output_dir, item)

                        if os.path.exists(dst):
                            final_dm.stream.write("ERROR: '{}' already exists at the destination ('{}').\n".format(src, dst))
                            final_dm.result = -1

                            continue

                        shutil.move(src, dst)

                    if final_dm.result != 0:
                        return final_dm.result
        
        return dm.result

# ----------------------------------------------------------------------
@CommandLine.EntryPoint
@CommandLine.Constraints( output_dir=CommandLine.DirectoryTypeInfo(),
                          output_stream=None,
                        )
def Clean( output_dir,
           output_stream=sys.stdout,
         ):
    with StreamDecorator(output_stream).DoneManager( line_prefix='',
                                                     prefix="\nResults: ",
                                                     suffix='\n',
                                                   ) as dm:
        if not _PreviousInstallation.Exists(output_dir):
            dm.stream.write("ERROR: '{}' is not a directory that was populated by AcquireBinaries.\n".format(output_dir))
            dm.result = -1

            return dm.result

        try:
            prev_installation = _PreviousInstallation.Load(output_dir)
        except Exception as ex:
            dm.stream.write("ERROR: {}.\n".format(StringHelpers.LeftJustify( str(ex),
                                                                             len("ERROR: "),
                                                                           )))
            dm.result = -1

            return dm.result

        dm.result = _CleanImpl( output_dir,
                                prev_installation.OriginalFileNames, 
                                dm.stream,
                              )
        if dm.result != 0:
            return dm.result            

        return dm.result

# ----------------------------------------------------------------------
@CommandLine.EntryPoint
@CommandLine.Constraints( app_name=CommandLine.StringTypeInfo(),
                          output_dir=CommandLine.DirectoryTypeInfo(ensure_exists=False),
                          unique_id=CommandLine.StringTypeInfo(),
                          output_stream=None,
                        )
def Verify( app_name,
            output_dir,
            unique_id,
            output_stream=sys.stdout,
          ):
    """Verifies that the unique_id associated with a previously installed output directory matches the expected value."""

    output_stream.write("Verifying '{}'...".format(app_name))
    with StreamDecorator(output_stream).DoneManager() as dm:
        if not _PreviousInstallation.Exists(output_dir):
            dm.stream.write("ERROR: The output directory '{}' associated with the application '{}' does not exist.\n".format(output_dir, app_name))
            dm.result = -1

            return dm.result

        previous_installation = _PreviousInstallation.Load(output_dir)
        if previous_installation.UniqueId != unique_id:
            sys.path.insert(0, os.getenv("DEVELOPMENT_ENVIRONMENT_FUNDAMENTAL"))
            with CallOnExit(lambda: sys.path.pop(0)):
                from RepositoryBootstrap import Constants

            dm.stream.write(textwrap.dedent(
                """\
                ERROR: The installation of '{}' at '{}' is not the expected version ('{}' != '{}').
                       Please run '{}' for this repository to update the installation.
                """).format( app_name,
                             output_dir,
                             previous_installation.UniqueId,
                             unique_id,
                             CurrentShell.CreateScriptName(Constants.SETUP_ENVIRONMENT_NAME),
                           ))
            dm.result = -1

            return dm.result

        return dm.result

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def _CleanImpl(output_dir, original_filenames, output_stream):
    output_stream.write("Cleaning previous content...")
    with output_stream.DoneManager() as dm:
        # Get the items to remove
        paths_to_remove = []

        dm.stream.write("Calculating items to remove...")
        with dm.stream.DoneManager( done_suffix=lambda: inflect.no("item", len(paths_to_remove)),
                                  ) as calculate_dm:
            for item in os.listdir(output_dir):
                if item not in original_filenames:
                    paths_to_remove.append(os.path.join(output_dir, item))

        if not paths_to_remove:
            return dm.result

        with dm.stream.SingleLineDoneManager("Removing items...") as this_dm:
            this_dm.result = TaskPool.Execute( [ TaskPool.Task(path_to_remove, (lambda path_to_remove=path_to_remove: 0 if FileSystem.RemoveItem(path_to_remove) else -1)) for path_to_remove in paths_to_remove ],
                                               this_dm.stream,
                                               progress_bar=True,
                                               num_concurrent_tasks=1,
                                             )
        return dm.result

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
class _PreviousInstallation(object):
    
    UNIQUE_ID_FILENAME                      = "__AcquireBinariesMetadata__.json"

    # ----------------------------------------------------------------------
    @classmethod
    def Exists(cls, output_dir):
        potential_filename = os.path.join(output_dir, cls.UNIQUE_ID_FILENAME)
        return os.path.isfile(potential_filename)

    # ----------------------------------------------------------------------
    @classmethod
    def Load(cls, output_dir):
        potential_filename = os.path.join(output_dir, cls.UNIQUE_ID_FILENAME)
        if not os.path.isfile(potential_filename):
            raise Exception("The file '{}' does not exist".format(potential_filename))

        try:
            with open(potential_filename) as f:
                content = json.load(f)

            unique_id = content["unique_id"]
            original_filenames = content["original_filenames"]

        except:
            raise Exception("The content in '{}' appears to be corrupt".format(potential_filename))

        return cls(unique_id, original_filenames)

    # ----------------------------------------------------------------------
    def __init__( self, 
                  unique_id, 
                  original_files=None,      # List of basenames that existed in the output dir before a binary was installed;
                                            # All files other than these will be deleted before applying a new version of the
                                            # binary.
                ):
        self.UniqueId                       = unique_id
        self.OriginalFileNames              = original_files or []

    # ----------------------------------------------------------------------
    def Save(self, output_dir):
        data = { "unique_id" : self.UniqueId,
                 "original_filenames" : self.OriginalFileNames,
               }

        with open(os.path.join(output_dir, self.UNIQUE_ID_FILENAME), 'w') as f:
            json.dump(data, f)

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
if __name__ == "__main__":
    try: sys.exit(CommandLine.Main())
    except KeyboardInterrupt: pass
