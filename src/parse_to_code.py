from pathlib import Path
from string import ascii_uppercase

from jinja2 import Template
from loguru import logger

from .scrape_telegram import APIInfo, get_parsed

# path to templates
TEMPLATES_PATH = Path("src/templates")
# extension of templates
TEMPLATES_EXTENSION = "jinja2"
# path to export populated templates to
OUTPUT_PATH = Path("out")
# where to import non-builtins from
IMPORT_FROM = ".types"


def change_root_directory(path_base: Path, path_from: Path, path_to: Path) -> Path:
    """Converts path_to to have path_from's path relative to path_base"""

    new_path = (
        path_to / path_from.relative_to(path_base) if path_from.parent else path_to
    )

    return new_path


def load_templates(
    path: Path = TEMPLATES_PATH, extension: str = TEMPLATES_EXTENSION
) -> dict[Path, Template]:
    """Loads all templates in the specified path recursively"""
    templates = {}

    for template_path in path.glob(f"**/*.{extension}"):
        with open(template_path) as f:
            templates[template_path] = Template(f.read())

    logger.info(f"Found {len(templates)} templates")
    return templates


def get_args(api_info: APIInfo) -> dict:
    """Get args to be passed to the template"""
    import_types: set[str] = set()

    for argument in api_info.arguments:
        if argument.builtin or not argument.argument_type:
            continue

        # if it contains symbols, skip it
        if not argument.argument_type.isidentifier():
            continue

        import_types.add(argument.argument_type)

    import_types_clean = list(sorted(import_types))

    extra_args = {"import_types": import_types_clean, "import_from": IMPORT_FROM}
    args = api_info.model_dump() | extra_args

    return args


def to_snake_case(string: str) -> str:
    """Converts string to snake_case notation"""
    # find upper case letters
    upper_case_letters = [i for i, c in enumerate(string) if c in ascii_uppercase]
    string = string.lower()

    if len(upper_case_letters) <= 1:
        return string

    for i in reversed(upper_case_letters):
        # don't add underscore if it's the first letter
        if i == 0:
            continue

        string = string[:i] + "_" + string[i:]

    return string


def populate_template(data: list[APIInfo], templates: dict[Path, Template]) -> None:
    """
    Generate models from Jinja2 templates located in the specified directory.
    """

    for template_path, template in templates.items():
        for api_info in data:
            args = get_args(api_info)
            rendered = template.render(**args)

            root_path = change_root_directory(
                TEMPLATES_PATH, template_path, OUTPUT_PATH
            )
            file_name = to_snake_case(api_info.title + ".py")
            output_path = root_path.with_name(file_name)
            # make the path if it doesn't exist yet
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with output_path.open("w") as f:
                f.write(rendered)

            logger.info(f"{output_path} has been generated.")


def scrape_to_template():
    data = get_parsed()
    templates = load_templates()
    populate_template(data, templates)


if __name__ == "__main__":
    scrape_to_template()
