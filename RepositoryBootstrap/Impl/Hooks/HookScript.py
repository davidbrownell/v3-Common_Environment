# ----------------------------------------------------------------------
# |  
# |  HookScript.py
# |  
# |  David Brownell <db@DavidBrownell.com>
# |      2018-05-06 10:09:50
# |  
# ----------------------------------------------------------------------
# |  
# |  Copyright David Brownell 2018-21.
# |  Distributed under the Boost Software License, Version 1.0.
# |  (See accompanying file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)
# |  
# ----------------------------------------------------------------------
"""Generic entry point for hooks"""

import os
import sys

from collections import OrderedDict

import six

import CommonEnvironment
from CommonEnvironment.CallOnExit import CallOnExit
from CommonEnvironment import CommandLine
from CommonEnvironment import Interface
from CommonEnvironment.StreamDecorator import StreamDecorator
from CommonEnvironment import StringHelpers

# ----------------------------------------------------------------------
_script_fullpath = CommonEnvironment.ThisFullpath()
_script_dir, _script_name = os.path.split(_script_fullpath)
# ----------------------------------------------------------------------

sys.path.insert(0, os.path.join(_script_dir, "GeneratedCode"))
with CallOnExit(lambda: sys.path.pop(0)):
    import HookScript_PythonJsonSerialization as Serialization

sys.path.insert(0, os.getenv("DEVELOPMENT_ENVIRONMENT_FUNDAMENTAL"))
with CallOnExit(lambda: sys.path.pop(0)):
    from RepositoryBootstrap import Constants
    from RepositoryBootstrap.Impl.ActivationData import ActivationData
    from RepositoryBootstrap.Impl import Utilities

# ----------------------------------------------------------------------
@CommandLine.EntryPoint
@CommandLine.Constraints( display_sentinel=CommandLine.StringTypeInfo(),
                          json_filename=CommandLine.FilenameTypeInfo(),
                          result_filename=CommandLine.FilenameTypeInfo(ensure_exists=False),
                          output_stream=None,
                        )
def Commit( display_sentinel,
            json_filename,
            result_filename,
            first=False,
            output_stream=sys.stdout,
          ):
    """Called prior to committing a change locally"""
    return _Impl( display_sentinel,
                  json_filename,
                  result_filename,
                  first,
                  output_stream,
                  Constants.HOOK_ENVIRONMENT_COMMIT_METHOD_NAME,
                  Serialization.Deserialize_Commit,
                )

# ----------------------------------------------------------------------
@CommandLine.EntryPoint
@CommandLine.Constraints( display_sentinel=CommandLine.StringTypeInfo(),
                          json_filename=CommandLine.FilenameTypeInfo(),
                          result_filename=CommandLine.FilenameTypeInfo(ensure_exists=False),
                          output_stream=None,
                        )
def Push( display_sentinel,
          json_filename,
          result_filename,
          first=False,
          output_stream=sys.stdout,
        ):
    """Called prior to pushing a local change(s) to the remote repository"""
    return _Impl( display_sentinel,
                  json_filename,
                  result_filename,
                  first,
                  output_stream,
                  Constants.HOOK_ENVIRONMENT_PUSH_METHOD_NAME,
                  Serialization.Deserialize_Push,
                )

# ----------------------------------------------------------------------
@CommandLine.EntryPoint
@CommandLine.Constraints( display_sentinel=CommandLine.StringTypeInfo(),
                          json_filename=CommandLine.FilenameTypeInfo(),
                          result_filename=CommandLine.FilenameTypeInfo(ensure_exists=False),
                          output_stream=None,
                        )
def Pull( display_sentinel,
          json_filename,
          result_filename,
          first=False,
          output_stream=sys.stdout,
        ):
    """Called prior to committing a change pushed from a client to the local repository"""
    return _Impl( display_sentinel,
                  json_filename,
                  result_filename,
                  first,
                  output_stream,
                  Constants.HOOK_ENVIRONMENT_PULL_METHOD_NAME,
                  Serialization.Deserialize_Pushed,
                )

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
def _Impl( display_sentinel,
           json_filename,
           result_filename,
           first,
           output_stream,
           method_name,
           parser,
         ):
    output_stream = StreamDecorator( output_stream,
                                     line_prefix=display_sentinel,
                                   )

    with open(json_filename) as f:
        try:
            data = parser(
                f.read(),
                is_root=False,
                always_include_optional=True,
            )
        except Exception as ex:
            output_stream.write("ERROR: {} ({})\n".format(str(ex), ex.stack))
            return -1

    output_stream.write("Parsing dependencies...")
    with output_stream.DoneManager():
        dependencies = ActivationData.Load(None, None, False).PrioritizedRepositories

    has_config_specific = False

    output_stream.write("Validating...")
    with output_stream.DoneManager() as dm:
        for index, repository_info in enumerate(dependencies):
            dm.stream.write("Processing '{}' ({} of {})...".format( repository_info.Name,
                                                                    index + 1,
                                                                    len(dependencies),
                                                                  ))
            with dm.stream.DoneManager() as this_dm:
                with Utilities.CustomMethodManager(os.path.join(repository_info.Root, Constants.HOOK_ENVIRONMENT_CUSTOMIZATION_FILENAME), method_name) as method:
                    if not method:
                        continue

                    args = OrderedDict([ ( "data", data ),
                                         ( "output_stream", this_dm.stream ),
                                       ])

                    # Get the method args to see if a configuration is requried
                    func_code = six.get_function_code(method)

                    if "configuration" in func_code.co_varnames[:func_code.co_argcount]:
                        args["configuration"] = repository_info.Configuration
                        has_config_specific = True
                    elif not first:
                        # Don't call a config-agnostic method more than once
                        continue

                    try:
                        this_dm.result = Interface.CreateCulledCallable(method)(args) or 0

                    except Exception as ex:
                        this_dm.stream.write(StringHelpers.LeftJustify( "ERROR: {}\n".format(str(ex).rstrip()),
                                                                        len("ERROR: "),
                                                                      ))
                        this_dm.result = -1

        with open(result_filename, 'w') as f:
            f.write('-1' if dm.result != 0 else '1' if has_config_specific else '0')

        return dm.result

# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
if __name__ == "__main__":
    try: sys.exit(CommandLine.Main())
    except KeyboardInterrupt: pass
