import json
import re
from pathlib import Path
from typing import Literal, Optional

import requests
from bs4 import BeautifulSoup
from loguru import logger
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from typing_extensions import Annotated

DOMAIN = "https://core.telegram.org"
API_PATH = "/bots/api"

# current file's directory
CACHE_PATH = Path("cache/response.txt")
RESULTS_PATH = Path("cache/results.json")

URL = f"{DOMAIN}{API_PATH}"

# If True, fields that are not specified to be optional or required will default to required
NONE_CONSIDERED_REQUIRED = True


ARGUMENT_TYPE_MAPPING = {
    "integer": "int",
    "string": "str",
    "float": "float",
    "boolean": "bool",
    "true": "bool",
    "false": "bool",
}

ARGUMENT_TYPE_BUILTINS = {
    "list",
    "int",
    "str",
    "float",
    "bool",
    "true",
    "false",
}


def convert_array_to_list(type_description: str) -> str:
    converted_desc = re.sub(r"Array of ", "list[", type_description)
    num_lists = converted_desc.count("list[")
    converted_desc += "]" * num_lists

    return converted_desc


def convert_or_to_union(type_description: str):
    def replace_with_union(match: re.Match[str]) -> str:
        if not match or len(match.groups()) < 2:
            return ""

        before_or = match.group(1)
        after_or = match.group(2)

        return f"Union[{before_or}, {after_or}]"

    pattern = r"(\w+) or (\w+)"
    if re.search(pattern, type_description) is None:
        return type_description

    converted_desc = re.sub(pattern, replace_with_union, type_description)

    return converted_desc


class Argument(BaseModel):
    argument_meta: Optional[Literal["parameter", "field"]] = None
    argument_type: Optional[str] = None
    # if argument_type is list[list[Message]], this will be Message
    # raw_types: Annotated[Optional[set[str]], Field(validate_default=True)] = None
    name: Optional[str] = None
    description: Optional[str] = None
    # whether the argument is required or not
    required: Annotated[Optional[bool], Field(validate_default=True)] = None
    # whether the argument is a python builtin or not
    builtin: Annotated[bool, Field(validate_default=True)] = False

    @field_validator("required", mode="before")
    @classmethod
    def validate_required(cls, v, info: ValidationInfo):
        if v is None:
            description = info.data.get("description")
            if description and description.lower().startswith("optional"):
                return False

            return NONE_CONSIDERED_REQUIRED

        if v.lower() == "optional":
            return False
        elif v.lower() == "yes":
            return True

        return v

    @field_validator("description", mode="before")
    @classmethod
    def handle_optional_description(cls, v, info: ValidationInfo):
        if v is not None and v.lower().startswith("optional"):
            info.data["required"] = False

        return v

    @field_validator("argument_type", mode="before")
    @classmethod
    def validate_argument_type(cls, v, info: ValidationInfo):
        if not isinstance(v, str):
            return v

        for key, value in ARGUMENT_TYPE_MAPPING.items():
            v = v.replace(key, value)
            v = v.replace(key.title(), value)
            v = v.replace(key.upper(), value)

        v = convert_array_to_list(v)
        v = convert_or_to_union(v)

        return v

    @field_validator("builtin", mode="after")
    @classmethod
    def validate_builtin(cls, v, info: ValidationInfo):
        argument_type = info.data["argument_type"]
        if argument_type and argument_type.lower() in ARGUMENT_TYPE_BUILTINS:
            return True

        return v

    @field_validator("name", mode="after")
    @classmethod
    def validate_name(cls, v, info: ValidationInfo):
        if not v:
            return None

        if v.lower() == "from":
            suffix = "_"
            if info.data.get("argument_type"):
                argument_type = info.data["argument_type"].lower()

                if "user" in argument_type:
                    suffix += "user"

            v += suffix

        return v

    # @field_validator("raw_types", mode="after")
    # @classmethod
    # def get_raw_types(cls, _, info: ValidationInfo):
    #     raw_types = set()
    #     parts = re.findall(r"\w+", info.data["argument_type"])
    #     for part in parts:
    #         if part in ARGUMENT_TYPE_BUILTINS:
    #             continue
    #
    #         raw_types.add(part)
    #
    #     return raw_types


class APIInfo(BaseModel):
    title: str
    description: str
    arguments: Optional[list[Argument]]


def get_page(url: str, cache_path=CACHE_PATH) -> str:
    """Get page content and return the content as a string"""
    if Path.exists(cache_path):
        logger.info(f"Using cached response for {url}")
        with open(cache_path, "r", encoding="utf-8") as f:
            return f.read()
    Path(cache_path).parent.mkdir(exist_ok=True)

    logger.info(f"Fetching {url}")
    response = requests.get(url)
    response.raise_for_status()
    text = response.text
    if not text:
        raise Exception("Response text is empty")

    # cache results
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(text)

    return text


def parse_page(content: str) -> list[APIInfo]:
    """Parse Page content and extract useful fields"""
    logger.info("Parsing...")
    bs = BeautifulSoup(content, "html.parser")
    titles = bs.find_all("h4")
    logger.info(f"Found {len(titles)} titles")

    results: list[APIInfo] = []
    unique_headers = set()
    for title in titles:
        # Check if the sequence h4 -> p -> table exists
        description = title.find_next_sibling()
        if not description or not description.name == "p":
            continue

        table = description.find_next_sibling()
        if not table or not table.name == "table":
            continue

        theads = [head.text for head in table.find("thead").find_all("th")]
        trows = table.find("tbody").find_all("tr")
        logger.debug(f"Found {len(trows)} rows for {title.text}")
        arguments = []
        for row in trows:
            tds = [d.text for d in row.find_all("td")]
            if len(tds) != len(theads):
                raise ValueError(
                    f"Header and data mismatch: {len(tds)} != {len(theads)}"
                )

            arg_info = {th.lower(): td for th, td in zip(theads, tds)}
            if "parameter" in arg_info:
                arg_info["argument_meta"] = "parameter"
                arg_info["name"] = arg_info["parameter"]
                del arg_info["parameter"]
            elif "field" in arg_info:
                arg_info["argument_meta"] = "field"
                arg_info["name"] = arg_info["field"]
                del arg_info["field"]

            if "type" in arg_info:
                arg_info["argument_type"] = arg_info["type"]
                del arg_info["type"]

            # sort the keys
            arg_info = {k: arg_info[k] for k in sorted(arg_info)}

            argument = Argument(**arg_info)
            arguments.append(argument)

        info = {
            "title": title.text,
            "description": description.text,
            "arguments": arguments,
        }
        api_info = APIInfo(**info)
        unique_headers.update(theads)
        results.append(api_info)

    logger.info(
        f"Found {len(results)} tables out of {len(titles)} titles ({len(results)/len(titles):.2%})"
    )
    logger.debug(f"Headers: {' - '.join(unique_headers)}")
    return results


def save_results(results: list[APIInfo], path: Path):
    """Save results to a json file"""
    logger.info(f"Saving results to {path}")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            [result.model_dump(mode="python") for result in results],
            f,
            indent=4,
            ensure_ascii=False,
        )


def get_argument_types(results: list[APIInfo]) -> set[str]:
    """Find all unique argument types present in the parsed data"""
    all_argument_types: set[str] = set()
    for result in results:
        if not result.arguments:
            continue

        argument_types = set(argument.argument_type for argument in result.arguments)
        all_argument_types.update(argument_types)

    return all_argument_types


def get_parsed(url: str = URL) -> list[APIInfo]:
    """Get data from Telegram and parse it"""
    content = get_page(url)
    results = parse_page(content)
    return results


def main():
    results = get_parsed(URL)
    save_results(results, RESULTS_PATH)
