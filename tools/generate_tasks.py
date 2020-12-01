
"""
This script generates Slicer Interfaces based on the CLI modules XML. CLI
modules are selected from the hardcoded list below and generated code is placed
in the cli_modules.py file (and imported in __init__.py). For this to work
correctly you must have your CLI executables in $PATH
"""
import keyword
import os
import shutil
import subprocess
import sys
import xml.dom.minidom

header = """\
\"""
Autogenerated file - DO NOT EDIT
If you spot a bug, please report it on the mailing list and/or change the generator.
\"""\n
"""

imports = """\
import attr
from nipype.interfaces.base import Directory, File, InputMultiPath, OutputMultiPath, traits
from pydra import ShellCommandTask
from pydra.engine.specs import SpecInfo, ShellSpec
import pydra\n\n
"""

setup = """\
def configuration(parent_package="", top_path=None):
    from numpy.distutils.misc_util import Configuration

    config = Configuration("{pkg_name}", parent_package, top_path)

    {sub_pks}

    return config

if __name__ == "__main__":
    from numpy.distutils.core import setup
    setup(**configuration(top_path="").todict())
"""

# launcher_space = ""
# if len({launcher})>0:
#     launcher_space = " "

template = """\
class {module_name}():
    \"""
{docstring}\
    \"""

    input_fields = [{input_fields}]
    output_fields = [{output_fields}]

    input_spec = SpecInfo(name="Input", fields=input_fields, bases=(ShellSpec,))
    output_spec = SpecInfo(name="Output", fields=output_fields, bases=(pydra.specs.ShellOutSpec,))

    task = ShellCommandTask(
        name="{module_name}",
        executable="{launcher}{module}",
        input_spec=input_spec,
        output_spec=output_spec,
    )
"""


def force_to_valid_python_variable_name(old_name):
    """  Valid c++ names are not always valid in python, so
    provide alternate naming

    >>> force_to_valid_python_variable_name('lambda')
    'opt_lambda'
    >>> force_to_valid_python_variable_name('inputVolume')
    'inputVolume'
    """
    new_name = old_name.strip()
    if new_name in keyword.kwlist:
        return f"opt_{new_name}"
    else:
        return new_name


def add_class_to_package(class_codes, class_names, module_name, package_dir):
    # with open(os.path.join(package_dir, "__init__.py"), mode="a+") as f:
    #     f.write(
    #         "from {module_name} import {class_names}\n".format(
    #             module_name=module_name, class_names=", ".join(class_names)
    #         )
    #     )
    with open(os.path.join(package_dir, f"{module_name}.py"), mode="w") as f:
        f.write(header)
        f.write(imports)
        f.write("\n\n".join(class_codes))


def crawl_code_struct(code_struct, package_dir):
    subpackages = []
    for k, v in code_struct.items():
        if isinstance(v, (str, bytes)):
            module_name = k.lower()
            class_name = k
            class_code = v
            add_class_to_package([class_code], [class_name], module_name, package_dir)
        else:
            l1 = {}
            l2 = {}
            for key in list(v.keys()):
                if isinstance(v[key], (str, bytes)):
                    l1[key] = v[key]
                else:
                    l2[key] = v[key]
            if l2:
                v = l2
                subpackages.append(k.lower())
                # with open(os.path.join(package_dir, "__init__.py"), mode="a+") as f:
                #     f.write(f"from {k.lower()} import *\n")
                new_pkg_dir = os.path.join(package_dir, k.lower())
                if os.path.exists(new_pkg_dir):
                    shutil.rmtree(new_pkg_dir)
                os.mkdir(new_pkg_dir)
                crawl_code_struct(v, new_pkg_dir)
                if l1:
                    for ik, iv in l1.items():
                        crawl_code_struct({ik: {ik: iv}}, new_pkg_dir)
            elif l1:
                v = l1
                module_name = k.lower()
                add_class_to_package(
                    list(v.values()), list(v.keys()), module_name, package_dir
                )
        if subpackages:
            with open(os.path.join(package_dir, "setup.py"), mode="w") as f:
                f.write(
                    setup.format(
                        pkg_name=package_dir.split("/")[-1],
                        sub_pks="\n    ".join(
                            [
                                f'config.add_data_dir("{sub_pkg}")'
                                for sub_pkg in subpackages
                            ]
                        ),
                    )
                )


def generate_all_classes(
    modules_list=[],
    launcher=[],
    redirect_x=False,
    mipav_hacks=False,
    xml_dir=None,
    output_dir=None,
):
    """ modules_list contains all the SEM compliant tools that should have wrappers created for them.
        launcher contains the command line prefix wrapper arguments needed to prepare
        a proper environment for each of the modules.
    """
    all_code = {}
    for module in modules_list:
        print("=" * 80)
        print(f"Generating Definition for module {module}")
        print("^" * 80)
        package, code, module = generate_class(
            module,
            launcher,
            redirect_x=redirect_x,
            mipav_hacks=mipav_hacks,
            xml_dir=xml_dir,
        )
        cur_package = all_code
        module_name = package.strip().split(" ")[0].split(".")[-1]
        for package in package.strip().split(" ")[0].split(".")[:-1]:
            if package not in cur_package:
                cur_package[package] = {}
            cur_package = cur_package[package]
        if module_name not in cur_package:
            cur_package[module_name] = {}
        cur_package[module_name][module] = code
    package_dir = output_dir if output_dir else os.getcwd()
    if not os.path.exists(package_dir):
        os.makedirs(package_dir)
    # if os.path.exists(os.path.join(package_dir, "__init__.py")):
    #     os.unlink(os.path.join(package_dir, "__init__.py"))
    crawl_code_struct(all_code, package_dir)
    os.system(f"black {package_dir}")


def generate_class(
    module,
    launcher,
    strip_module_name_prefix=True,
    redirect_x=False,
    mipav_hacks=False,
    xml_dir=None,
):
    if xml_dir:
        dom = dom_from_xml(module, xml_dir)
    else:
        dom = dom_from_binary(module, launcher, mipav_hacks=mipav_hacks)
    if strip_module_name_prefix:
        module_name = module.split(".")[-1]
    else:
        module_name = module
    inputTraits = []
    outputTraits = []
    outputs_filenames = {}

    # self._outputs_nodes = []

    docstring = ""

    for desc_str in [
        "title",
        "category",
        "description",
        "version",
        "documentation-url",
        "license",
        "contributor",
        "acknowledgements",
    ]:
        el = dom.getElementsByTagName(desc_str)
        if el and el[0].firstChild and el[0].firstChild.nodeValue.strip():
            docstring += "    {desc_str}: {el}\n".format(
                desc_str=desc_str, el=el[0].firstChild.nodeValue.strip()
            )
        if desc_str == "category":
            category = el[0].firstChild.nodeValue.strip()

    for paramGroup in dom.getElementsByTagName("parameters"):
        indices = paramGroup.getElementsByTagName("index")
        max_index = 0
        for index in indices:
            if int(index.firstChild.nodeValue) > max_index:
                max_index = int(index.firstChild.nodeValue)
        for param in paramGroup.childNodes:
            if param.nodeName in ["label", "description", "#text", "#comment"]:
                continue
            traitsParams = {}

            longFlagNode = param.getElementsByTagName("longflag")
            if longFlagNode:
                # Prefer to use longFlag as name if it is given, rather than the parameter name
                longFlagName = longFlagNode[0].firstChild.nodeValue
                # SEM automatically strips prefixed "--" or "-" from from xml before processing
                # we need to replicate that behavior here The following
                # two nodes in xml have the same behavior in the program
                # <longflag>--test</longflag>
                # <longflag>test</longflag>
                longFlagName = longFlagName.lstrip(" -").rstrip(" ")
                name = longFlagName
                name = force_to_valid_python_variable_name(name)
                traitsParams["argstr"] = f"--{longFlagName} "
            else:
                name = param.getElementsByTagName("name")[0].firstChild.nodeValue
                name = force_to_valid_python_variable_name(name)
                if param.getElementsByTagName("index"):
                    traitsParams["argstr"] = ""
                else:
                    traitsParams["argstr"] = f"--{name} "

            if (
                param.getElementsByTagName("description")
                and param.getElementsByTagName("description")[0].firstChild
            ):
                traitsParams["help_string"] = (
                    param.getElementsByTagName("description")[0]
                    .firstChild.nodeValue.replace('"', '\\"')
                    .replace("\n", ", ")
                )

            # argsDict = {
            #     "directory": "%s",
            #     "file": "%s",
            #     "integer": "%d",
            #     "double": "%f",
            #     "float": "%f",
            #     "image": "%s",
            #     "transform": "%s",
            #     "boolean": "",
            #     "string-enumeration": "%s",
            #     "string": "%s",
            #     "integer-enumeration": "%s",
            #     "table": "%s",
            #     "point": "%s",
            #     "region": "%s",
            #     "geometry": "%s",
            # }

            # if param.nodeName.endswith("-vector"):
            #     traitsParams["argstr"] += "%s"
            # else:
            #     traitsParams["argstr"] += argsDict[param.nodeName]

            index = param.getElementsByTagName("index")
            if index:
                traitsParams["position"] = int(index[0].firstChild.nodeValue) - (
                    max_index + 1
                )

            desc = param.getElementsByTagName("description")
            if index:
                traitsParams["help_string"] = desc[0].firstChild.nodeValue

            typesDict = {
                "integer": "traits.Int",
                "double": "traits.Float",
                "float": "traits.Float",
                "image": "File",
                "transform": "File",
                "boolean": "traits.Bool",
                "string": "traits.Str",
                "file": "File",
                "geometry": "File",
                "directory": "Directory",
                "table": "File",
                "point": "traits.List",
                "region": "traits.List",
            }

            if param.nodeName.endswith("-enumeration"):
                type = "traits.Enum"
                values = [
                    '"{value}"'.format(
                        value=str(el.firstChild.nodeValue).replace('"', "")
                    )
                    for el in param.getElementsByTagName("element")
                ]
            elif param.nodeName.endswith("-vector"):
                type = "InputMultiPath"
                if param.nodeName in [
                    "file",
                    "directory",
                    "image",
                    "geometry",
                    "transform",
                    "table",
                ]:
                    values = [
                        "{type}(exists=True)".format(
                            type=typesDict[param.nodeName.replace("-vector", "")]
                        )
                    ]
                else:
                    values = [typesDict[param.nodeName.replace("-vector", "")]]
                if mipav_hacks is True:
                    traitsParams["sep"] = ";"
                else:
                    traitsParams["sep"] = ","
            elif param.getAttribute("multiple") == "true":
                type = "InputMultiPath"
                if param.nodeName in [
                    "file",
                    "directory",
                    "image",
                    "geometry",
                    "transform",
                    "table",
                ]:
                    values = [
                        "{type}(exists=True)".format(type=typesDict[param.nodeName])
                    ]
                elif param.nodeName in ["point", "region"]:
                    values = [
                        "{type}(traits.Float(), minlen=3, maxlen=3)".format(
                            type=typesDict[param.nodeName]
                        )
                    ]
                else:
                    values = [typesDict[param.nodeName]]
                traitsParams["argstr"] += "..."
            else:
                values = []
                type = typesDict[param.nodeName]

            if param.nodeName in [
                "file",
                "directory",
                "image",
                "geometry",
                "transform",
                "table",
            ]:
                if not param.getElementsByTagName("channel"):
                    raise RuntimeError(
                        "Insufficient XML specification: each element of type 'file', 'directory', 'image', 'geometry', 'transform',  or 'table' requires 'channel' field.\n{0}".format(
                            traitsParams
                        )
                    )
                elif (
                    param.getElementsByTagName("channel")[0].firstChild.nodeValue
                    == "output"
                ):
                    # traitsParams["hash_files"] = False
                    inputTraits.append(
                        '("{name}", attr.ib(type={type}, metadata={{{params}}}))'.format(
                            name=name, type=type, params=parse_params(traitsParams)
                        )
                    )
                    # traitsParams["exists"] = True
                    traitsParams.pop("argstr")
                    traitsParams["output_file_template"] = f"{{{name}}}_{module_name}".replace("output", "input")
 		    # traitsParams.pop("hash_files")
                    outputTraits.append(
                        '("{name}", attr.ib(type={type}, metadata={{{params}}}))'.format(
                            name=name,
                            type=f'pydra.specs.{type.replace("Input", "Output")}',
                            params=parse_params(traitsParams),
                        )
                    )

                    outputs_filenames[name] = gen_filename_from_param(param, name)
                elif (
                    param.getElementsByTagName("channel")[0].firstChild.nodeValue
                    == "input"
                ):
                    # if param.nodeName in [
                    #     "file",
                    #     "directory",
                    #     "image",
                    #     "geometry",
                    #     "transform",
                    #     "table",
                    # ] and type not in ["InputMultiPath", "traits.List"]:
                        # traitsParams["exists"] = True
                    inputTraits.append(
                        '("{name}", attr.ib(type={type}, metadata={{{params}}}))'.format(
                            name=name, type=type, params=parse_params(traitsParams)
                        )
                    )
                else:
                    raise RuntimeError(
                        "Insufficient XML specification: each element of type 'file', 'directory', 'image', 'geometry', 'transform',  or 'table' requires 'channel' field to be in ['input','output'].\n{0}".format(
                            traitsParams
                        )
                    )
            else:  # For all other parameter types, they are implicitly only input types
                inputTraits.append(
                    '("{name}", attr.ib(type={type}, metadata={{{params}}}))'.format(
                        name=name, type=type, params=parse_params(traitsParams)
                    )
                )

    if mipav_hacks:
        blacklisted_inputs = ["maxMemoryUsage"]
        inputTraits = [
            trait for trait in inputTraits if trait.split()[0] not in blacklisted_inputs
        ]

        compulsory_inputs = [
            'xDefaultMem = traits.Int(help_string="Set default maximum heap size", argstr="-xDefaultMem %d")',
            'xMaxProcess = traits.Int(1, help_string="Set default maximum number of processes.", argstr="-xMaxProcess %d", usedefault=True)',
        ]
        inputTraits += compulsory_inputs

    input_fields = ""
    for trait in inputTraits:
        input_fields += f"{trait}, "

    output_fields = ""
    for trait in outputTraits:
        output_fields += f"{trait}, "

    output_filenames = ",".join(
        [f'"{key}":"{value}"' for key, value in outputs_filenames.items()]
    )

    main_class = template.format(
        module_name=module_name,
        docstring=docstring,
        input_fields=input_fields,
        output_fields=output_fields,
        launcher=" ".join(launcher),
        module=module,
    )

    return category, main_class, module_name


def dom_from_binary(module, launcher, mipav_hacks=False):
    #        cmd = CommandLine(command = "Slicer3", args="--launch %s --xml"%module)
    #        ret = cmd.run()
    command_list = launcher[:]  # force copy to preserve original
    command_list.extend([module, "--xml"])
    final_command = " ".join(command_list)
    xmlReturnValue = subprocess.Popen(
        final_command, stdout=subprocess.PIPE, shell=True
    ).communicate()[0]
    if mipav_hacks:
        # workaround for a jist bug https://www.nitrc.org/tracker/index.php?func=detail&aid=7234&group_id=228&atid=942
        new_xml = ""
        replace_closing_tag = False
        for line in xmlReturnValue.splitlines():
            if line.strip() == "<file collection: semi-colon delimited list>":
                new_xml += "<file-vector>\n"
                replace_closing_tag = True
            elif replace_closing_tag and line.strip() == "</file>":
                new_xml += "</file-vector>\n"
                replace_closing_tag = False
            else:
                new_xml += f"{line}\n"

        xmlReturnValue = new_xml

        # workaround for a JIST bug https://www.nitrc.org/tracker/index.php?func=detail&aid=7233&group_id=228&atid=942
        if xmlReturnValue.strip().endswith("XML"):
            xmlReturnValue = xmlReturnValue.strip()[:-3]
        if xmlReturnValue.strip().startswith("Error: Unable to set default atlas"):
            xmlReturnValue = xmlReturnValue.strip()[
                len("Error: Unable to set default atlas") :
            ]
    try:
        dom = xml.dom.minidom.parseString(xmlReturnValue.strip())
    except Exception as e:
        print(xmlReturnValue.strip())
        raise e
    return dom


#        if ret.runtime.returncode == 0:
#            return xml.dom.minidom.parseString(ret.runtime.stdout)
#        else:
#            raise Exception(cmd.cmdline + " failed:\n%s"%ret.runtime.stderr)


def dom_from_xml(module, xml_dir):
    try:
        dom = xml.dom.minidom.parse(os.path.join(xml_dir, f"{module}.xml"))
    except Exception as e:
        print(os.path.join(xml_dir, f"{module}.xml"))
        raise e
    return dom


def parse_params(params):
    list = []
    for key, value in params.items():
        if isinstance(value, (str, bytes)):
            list.append(
                '"{key}": "{value}"'.format(key=key, value=value.replace('"', "'"))
            )
        else:
            list.append(f'"{key}": "{value}"')

    return ", ".join(list)


def parse_values(values):
    values = [f"{value}" for value in values]
    if len(values) > 0:
        return ", ".join(values) + ", "
    else:
        return ""


def gen_filename_from_param(param, base):
    fileExtensions = param.getAttribute("fileExtensions")
    if fileExtensions:
        # It is possible that multiple file extensions can be specified in a
        # comma separated list,  This will extract just the first extension
        firstFileExtension = fileExtensions.split(",")[0]
        ext = firstFileExtension
    else:
        ext = {
            "image": ".nii",
            "transform": ".mat",
            "file": "",
            "directory": "",
            "geometry": ".vtk",
        }[param.nodeName]
    return base + ext


if __name__ == "__main__":
    # NOTE:  For now either the launcher needs to be found on the default path, or
    # every tool in the modules list must be found on the default path
    # AND calling the module with --xml must be supported and compliant.
    modules_list = [
        # "ACPCTransform",
        # "AddScalarVolumes",
        # "BRAINSABC",
        # "BRAINSAlignMSP",
        # "BRAINSCleanMask",
        # "BRAINSClipInferior",
        "BRAINSConstellationDetector",
        # "BRAINSConstellationDetectorGUI",
        # "BRAINSConstellationLandmarksTransform",
        # "BRAINSConstellationModeler",
        # "BRAINSCreateLabelMapFromProbabilityMaps",
        # "BRAINSDWICleanup",
        # "BRAINSEyeDetector",
        # "BRAINSFit",
        # "BRAINSInitializedControlPoints",
        # "BRAINSLabelStats",
        # "BRAINSLandmarkInitializer",
        # "BRAINSLinearModelerEPCA",
        # "BRAINSLmkTransform",
        # "BRAINSMultiModeSegment",
        # "BRAINSMultiSTAPLE",
        # "BRAINSMush",
        # "BRAINSPosteriorToContinuousClass",
        # "BRAINSROIAuto",
         "BRAINSResample",
        # "BRAINSResize",
        # "BRAINSSnapShotWriter",
        # "BRAINSStripRotation",
        # "BRAINSTalairach",
        # "BRAINSTalairachMask",
        # "BRAINSTransformConvert",
        # "BRAINSTransformFromFiducials",
        # "BRAINSTrimForegroundInDirection",
        # "BinaryMaskEditorBasedOnLandmarks",
        # "CLIROITest",
        # "CastScalarVolume",
        # "CheckerBoardFilter",
        # "ComputeReflectiveCorrelationMetric",
        # "CreateDICOMSeries",
        # "CurvatureAnisotropicDiffusion",
        # "DWICompare",
        # # "DWIConvert",
        # "DWISimpleCompare",
        # "DiffusionTensorTest",
        # "ESLR",
        # # "ExecutionModelTour",
        # "ExpertAutomatedRegistration",
        # # "ExtractSkeleton",
        # "FiducialRegistration",
        # "FindCenterOfBrain",
        # "GaussianBlurImageFilter",
        # "GenerateAverageLmkFile",
        # "GenerateEdgeMapImage",
        # "GenerateLabelMapFromProbabilityMap",
        # "GeneratePurePlugMask",
        # "GradientAnisotropicDiffusion",
        # "GrayscaleFillHoleImageFilter",
        # "GrayscaleGrindPeakImageFilter",
        # "GrayscaleModelMaker",
        # "HistogramMatching",
        # "ImageLabelCombine",
        # "LabelMapSmoothing",
        # "LandmarksCompare",
        # "MaskScalarVolume",
        # "MedianImageFilter",
        # "MergeModels",
        # "ModelMaker",
        # "ModelToLabelMap",
        # "MultiplyScalarVolumes",
        # "N4ITKBiasFieldCorrection",
        # "OrientScalarVolume",
        # "PETStandardUptakeValueComputation",
        # "PerformMetricTest",
        # "ProbeVolumeWithModel",
        # "ResampleDTIVolume",
        # "ResampleScalarVectorDWIVolume",
        # "ResampleScalarVolume",
        # "RobustStatisticsSegmenter",
        # "SimpleRegionGrowingSegmentation",
        # "SubtractScalarVolumes",
        # "TestGridTransformRegistration",
        # "ThresholdScalarVolume",
        # "VotingBinaryHoleFillingImageFilter",
        # "compareTractInclusion",
        # "extractNrrdVectorIndex",
        # "fcsv_to_hdf5",
        # "gtractAnisotropyMap",
        # "gtractAverageBvalues",
        # "gtractClipAnisotropy",
        # "gtractCoRegAnatomy",
        # "gtractCoRegAnatomyBspline",
        # "gtractCoRegAnatomyRigid",
        # "gtractConcatDwi",
        # "gtractCopyImageOrientation",
        # "gtractCoregBvalues",
        # "gtractCostFastMarching",
        # "gtractCreateGuideFiber",
        # "gtractFastMarchingTracking",
        # "gtractFiberTracking",
        # "gtractFreeTracking",
        # "gtractGraphSearchTracking",
        # "gtractGuidedTracking",
        # "gtractImageConformity",
        # "gtractInvertBSplineTransform",
        # "gtractInvertDisplacementField",
        # "gtractInvertRigidTransform",
        # "gtractResampleAnisotropy",
        # "gtractResampleB0",
        # "gtractResampleCodeImage",
        # "gtractResampleDWIInPlace",
        # "gtractResampleFibers",
        # "gtractStreamlineTracking",
        # "gtractTensor",
        # "gtractTransformToDisplacementField",
        # "insertMidACPCpoint",
        # "landmarksConstellationAligner",
        # "landmarksConstellationWeights",
        # "simpleEM",
    ]

    launcher = []

    arguments = sys.argv[1:]
    num_arguments = len(arguments)

    if num_arguments <= 2:
        output_dir, xml_dir = arguments + [None] * (2 - num_arguments)
    else:
        raise ValueError(
            f"expected at most 2 arguments [output directory, xml directory], received {num_arguments} arguments: {arguments}"
        )

    # SlicerExecutionModel compliant tools that are usually statically built, and don't need the Slicer3 --launcher
    generate_all_classes(
        modules_list=modules_list,
        launcher=launcher,
        xml_dir=xml_dir,
        output_dir=output_dir,
    )
    # Tools compliant with SlicerExecutionModel called from the Slicer environment (for shared lib compatibility)
    # launcher = ['/home/raid3/gorgolewski/software/slicer/Slicer', '--launch']
    # generate_all_classes(modules_list=modules_list, launcher=launcher)
    # generate_all_classes(modules_list=['BRAINSABC'], launcher=[] )
