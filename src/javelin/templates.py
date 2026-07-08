import glob
import os
import re
import string
import typing


class PathTemplate:
    @staticmethod
    def compile_templates(root: str, templates: dict[str, str]):
        return compile_templates(root, templates)

    def __init__(self, name: str, root_dir: str, fmt_string: str):
        self.__root = root_dir
        self.__name = name
        self.__compile_result = compile_template_string(fmt_string)

    @property
    def name(self):
        return self.__name

    @property
    def keys(self):
        return self.__compile_result.keys.copy()

    def format(self, **fields) -> str:
        return self.format_map(fields)

    def format_map(self, fields):
        data = {}
        for key in self.__compile_result.keys:
            if key not in fields:
                data[key] = self.__compile_result.defaults[key]
            else:
                data[key] = self.__compile_result.formatters[key](fields[key])

        return os.path.join(self.__root, self.__compile_result.format_str.format_map(data))

    def match(self, path: str):
        if not path.startswith(self.__root):
            return None

        rel = os.path.relpath(path, self.__root)

        if match := self.__compile_result.regex_pattern.match(rel):
            result = {}
            for k, v in match.groupdict().items():
                result[k] = self.__compile_result.parsers[k](v)
            return result

    def fullmatch(self, path: str):
        if not path.startswith(self.__root):
            return None

        rel = os.path.relpath(path, self.__root)

        if match := self.__compile_result.regex_pattern.fullmatch(rel):
            result = {}
            for k, v in match.groupdict().items():
                result[k] = self.__compile_result.parsers[k](v)
            return result

    def glob(self, fields: dict) -> typing.Iterator[tuple[str, dict]]:
        data = {}
        for key in self.__compile_result.keys:
            if key in fields:
                data[key] = self.__compile_result.formatters[key](fields[key])
            else:
                data[key] = "*"

        pathname = os.path.join(self.__root, self.__compile_result.format_str.format_map(data))
        print(pathname)
        for path in glob.glob(pathname):
            if match := self.fullmatch(path):
                yield path, match


_formatter = string.Formatter()


class CompileResult(typing.NamedTuple):
    format_str: str
    regex_pattern: re.Pattern[str]
    formatters: dict[str, typing.Callable[[object], str]]
    parsers: dict[str, typing.Callable[[str], object]]
    defaults: dict[str, object]
    keys: set[str]


def frame_formatter(value: int | str, padding: int) -> str:
    if isinstance(value, int):
        return str(value).zfill(padding)
    else:
        return value


def frame_parser(value: str) -> int | str:
    try:
        return int(value)
    except Exception:
        return value


def int_formatter(value: int, padding: int) -> str:
    if isinstance(value, int):
        return str(value).zfill(padding)
    else:
        raise TypeError(f"expected: int, got:{value}")


def int_parser(value: str) -> int:
    return int(value)


def compile_template_string(template_string: str):
    fmt_frags = []
    pattern_frags = []

    seen = set()
    defaults = {}
    parsers = {}
    parsers = {}
    formatters = {}

    for literal, field_name, format_spec, _ in _formatter.parse(template_string):
        fmt_frags.append(literal)
        pattern_frags.append(re.escape(literal))

        if field_name:
            if field_name in seen:
                # insert a back-reference into pattern frags
                pattern_frags.append(rf"(?P={field_name})")
                fmt_frags.append("{" + field_name + "}")
                continue

            seen.add(field_name)

            if format_spec:
                # f:8:%08d or f:8:# or f:8:####
                if match := re.match(r"f:(?P<padding>\d+):(?P<default>(\%\d+d)|(#+))", format_spec):
                    padding = int(match.group(1))
                    default = match.group(2)
                    fragment = "{" + field_name + "}"
                    fmt_frags.append(fragment)
                    pattern_frags.append("(?P<" + field_name + ">[0-9]+|#+|%0[0-9]+d)")
                    defaults[field_name] = default

                    parsers[field_name] = frame_parser
                    formatters[field_name] = lambda v, p=padding: frame_formatter(v, p)

                elif match := re.match(r"d:(?P<padding>\d+)", format_spec):
                    padding = int(match.group(1))
                    fmt_frags.append("{" + field_name + "}")
                    pattern_frags.append(f"(?P<{field_name}>[0-9]+)")
                    parsers[field_name] = int_parser
                    formatters[field_name] = lambda v, p=padding: int_formatter(v, p)

                else:
                    raise ValueError("unsupported format spec", format_spec)
            else:
                parsers[field_name] = str
                formatters[field_name] = str
                fmt_frags.append("{" + field_name + "}")
                pattern_frags.append(f"(?P<{field_name}>[A-Za-z][A-Za-z0-9_]*)")

    format_str = "".join(fmt_frags)
    regex_str = "".join(pattern_frags)
    regex_pattern = re.compile(regex_str)

    return CompileResult(format_str, regex_pattern, formatters, parsers, defaults, seen)


_TEMPLATE_REF = re.compile(r"<([^>]+)>")


def compile_templates(root: str, templates: dict[str, str]) -> dict[str, PathTemplate]:
    """Expand <name> references and compile each entry into a PathTemplate under root."""
    expanded: dict[str, str] = {}

    def _expand(name: str, visiting: frozenset[str]) -> str:
        if name in expanded:
            return expanded[name]
        if name not in templates:
            raise KeyError(f"Unknown template reference: <{name}>")
        if name in visiting:
            raise ValueError(f"Circular template reference: <{name}>")

        value = _TEMPLATE_REF.sub(
            lambda m: _expand(m.group(1), visiting | {name}),
            templates[name],
        )
        expanded[name] = value
        return value

    for name in templates:
        _expand(name, frozenset())

    return {name: PathTemplate(name, root, fmt) for name, fmt in expanded.items()}
