"""Shared module parsing and build primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..build_step import BuildStep



class ModuleError(Exception):
    """Raised when a module definition is invalid."""
    pass


@dataclass
class ModuleBase:
    """Base class for all module types."""
    type: str
    defaults: dict[str, Any] = field(default_factory=dict)
    
    def merge_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        """Merge defaults with user-provided data (user data takes precedence)."""
        if not self.defaults:
            return data
        merged = {**self.defaults, **data}
        return merged
    
    def build(self) -> list[BuildStep]:
        """Generate build steps for this module.
        
        Returns a list of BuildStep objects that will be executed in order.
        Subclasses should override this method to provide module-specific build logic.
        """
        raise NotImplementedError(f"{self.type} module must implement build()")
    
    def to_dict(self) -> dict[str, Any]:
        """Convert module back to dict for serialization."""
        result = {"type": self.type}
        if self.defaults:
            result["defaults"] = self.defaults
        # Add all non-None fields from the dataclass
        for field_name in self.__dataclass_fields__:
            if field_name in ("type", "defaults"):
                continue
            value = getattr(self, field_name)
            if value is not None:
                result[field_name] = value
        return result

    def capabilities(self) -> dict[str, str]:
        """Return capability slots provided by this module."""
        return {}


MODULE_FIELDS: dict[str, set[str]] = {
    "chocolatey": {"type", "defaults", "install", "packages", "packageSource"},
    "install": {"type", "defaults", "source", "installer", "sha256", "args", "workingDirectory", "environment", "timeout", "expectedExitCodes"},
    "registry": {"type", "defaults", "file", "changes", "sha256", "view", "user"},
    "extract": {"type", "defaults", "source", "target", "sha256", "maxBytes", "backend"},
    "check": {"type", "defaults", "file", "command"},
    "dll": {"type", "defaults", "install", "overrides", "evidence"},
    "iso": {"type", "defaults", "action", "id", "source", "drive", "backend", "mountPath", "sha256"},
    "winetricks": {"type", "defaults", "verbs"},
    "portable": {"type", "defaults", "source", "target"},
    "files": {"type", "defaults", "mappings"},
    "script": {"type", "defaults", "run", "file", "sha256", "shell", "workingDirectory", "environment", "timeout", "user", "outputs"},
}

FILES_MAPPING_FIELDS = {"source", "target", "sha256", "mode"}
FILES_MAPPING_MODES = {"copy", "merge"}


def _reject_unknown_module_fields(data: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ModuleError(f"unknown module field: {location}.{unknown[0]}")


def _required_str(data: dict[str, Any], key: str, location: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ModuleError(f"{location}.{key} must be a non-empty string")
    return value


def _optional_str(data: dict[str, Any], key: str, location: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ModuleError(f"{location}.{key} must be a non-empty string when present")
    return value


def _string_list(value: Any, location: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ModuleError(f"{location} must be a list of non-empty strings")
    return value


def _validate_files_mappings(mappings: Any, location: str) -> None:
    if not isinstance(mappings, list) or not mappings:
        raise ModuleError(f"{location}.mappings must be a non-empty list")
    for mapping_index, mapping in enumerate(mappings):
        mapping_location = f"{location}.mappings[{mapping_index}]"
        if not isinstance(mapping, dict):
            raise ModuleError(f"{mapping_location} must be an object")
        _reject_unknown_module_fields(mapping, FILES_MAPPING_FIELDS, mapping_location)
        _required_str(mapping, "source", mapping_location)
        _required_str(mapping, "target", mapping_location)
        sha = _optional_str(mapping, "sha256", mapping_location)
        if sha is not None:
            import re
            if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
                raise ModuleError(f"{mapping_location}.sha256 must be 64 hexadecimal characters")
        mode = mapping.get("mode", "copy")
        if mode not in FILES_MAPPING_MODES:
            raise ModuleError(f"{mapping_location}.mode must be one of: " + ", ".join(sorted(FILES_MAPPING_MODES)))


def _validate_common_module_data(module_type: str, data: dict[str, Any], index: int) -> None:
    location = f"modules[{index}]"
    allowed = MODULE_FIELDS[module_type]
    _reject_unknown_module_fields(data, allowed, location)
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ModuleError(f"{location}.defaults must be a dict")
    _reject_unknown_module_fields(defaults, allowed - {"type", "defaults"}, f"{location}.defaults")

    if module_type == "install":
        _required_str(data, "source", location)
        if data.get("installer") is not None and data["installer"] not in {"exe", "msi"}:
            raise ModuleError(f"{location}.installer must be exe or msi")
        sha = _optional_str(data, "sha256", location)
        if sha and __import__("re").fullmatch(r"[0-9a-fA-F]{64}", sha) is None:
            raise ModuleError(f"{location}.sha256 must be 64 hexadecimal characters")
        if "args" in data:
            _string_list(data["args"], f"{location}.args")
        _optional_str(data, "workingDirectory", location)
        if "environment" in data and (not isinstance(data["environment"], dict) or
            any(not isinstance(k, str) or not __import__("re").fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) or not isinstance(v, str)
                for k, v in data["environment"].items())):
            raise ModuleError(f"{location}.environment must map POSIX variable names to strings")
        if "timeout" in data and (type(data["timeout"]) is not int or data["timeout"] <= 0):
            raise ModuleError(f"{location}.timeout must be a positive integer")
        codes = data.get("expectedExitCodes", [0])
        if not isinstance(codes, list) or not codes or any(type(code) is not int or code < 0 or code > 255 for code in codes):
            raise ModuleError(f"{location}.expectedExitCodes must be a non-empty list of exit codes 0..255")
        if data.get("timeout") and set(codes) & {124, 137}:
            raise ModuleError(f"{location}.expectedExitCodes cannot accept timeout exit codes 124 or 137")
    elif module_type == "iso":
        import re
        action = data.get("action", "mount")
        if action not in {"mount", "unmount"}:
            raise ModuleError(f"{location}.action must be mount or unmount")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", _required_str(data, "id", location)):
            raise ModuleError(f"{location}.id must be a safe resource identifier")
        if action == "mount":
            _required_str(data, "source", location)
            _required_str(data, "mountPath", location)
            if data.get("backend", "host") != "host":
                raise ModuleError(f"{location}.backend only supports operator host mount; no privileged fallback")
            drive = _required_str(data, "drive", location)
            if not re.fullmatch(r"[D-Yd-y]", drive):
                raise ModuleError(f"{location}.drive must be one drive letter D through Y")
            sha = _optional_str(data, "sha256", location)
            if sha and not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
                raise ModuleError(f"{location}.sha256 must be 64 hexadecimal characters")
        elif set(data) & {"source", "drive", "mountPath", "backend", "sha256"}:
            raise ModuleError(f"{location}.unmount only accepts id and action")
    elif module_type == "registry":
        if bool(data.get("file")) == bool(data.get("changes")):
            raise ModuleError(f"{location} requires exactly one of file or changes")
        _optional_str(data, "file", location)
        sha = _optional_str(data, "sha256", location)
        if sha and __import__("re").fullmatch(r"[0-9a-fA-F]{64}", sha) is None:
            raise ModuleError(f"{location}.sha256 must be 64 hexadecimal characters")
        if sha and not data.get("file"):
            raise ModuleError(f"{location}.sha256 requires file")
        if data.get("view", "default") != "default":
            raise ModuleError(f"{location}.view currently supports only default Wine prefix view")
        if data.get("user", "application") != "application":
            raise ModuleError(f"{location}.user currently supports only application context")
        if data.get("changes") is not None:
            changes = data["changes"]
            if not isinstance(changes, list) or not changes:
                raise ModuleError(f"{location}.changes must be a non-empty list")
            for change in changes:
                if not isinstance(change, dict) or set(change) - {"action", "key", "name", "type", "value"}:
                    raise ModuleError(f"{location}.changes contains an unknown field")
                if change.get("action") not in {"set", "deleteValue", "deleteKey"}:
                    raise ModuleError(f"{location}.changes action must be set, deleteValue or deleteKey")
                _required_str(change, "key", f"{location}.changes")
                if change["action"] == "set" and (change.get("type", "string") not in {"string", "expandString", "dword", "qword", "binary"} or "value" not in change):
                    raise ModuleError(f"{location}.changes set requires a supported type and value")
                if change["action"] == "deleteKey" and set(change) & {"name", "type", "value"}:
                    raise ModuleError(f"{location}.changes deleteKey cannot name a value")
            from .registry import compile_reg
            compile_reg(changes)
    elif module_type == "extract":
        source = _required_str(data, "source", location)
        from .extract import ExtractModule
        try:
            archive_format = ExtractModule(source=source).archive_format()
        except ValueError as exc:
            raise ModuleError(f"{location}.source: {exc}") from exc
        backend = data.get("backend")
        if archive_format == "iso" and backend not in {"bsdtar", "7z"}:
            raise ModuleError(f"{location}.backend must explicitly select bsdtar or 7z for ISO")
        if archive_format != "iso" and backend is not None:
            raise ModuleError(f"{location}.backend is only needed for ISO")
        target = _required_str(data, "target", location)
        if not target.startswith("/work/"):
            from .paths import validate_linux_output
            validate_linux_output(target)
        if ".." in target.split("/") or "\\" in target:
            raise ModuleError(f"{location}.target is unsafe")
        if data.get("maxBytes") is not None and (type(data["maxBytes"]) is not int or not 1 <= data["maxBytes"] <= 8 * 1024**3):
            raise ModuleError(f"{location}.maxBytes must be 1..8589934592")
        sha = _optional_str(data, "sha256", location)
        if sha and __import__("re").fullmatch(r"[0-9a-fA-F]{64}", sha) is None:
            raise ModuleError(f"{location}.sha256 must be 64 hexadecimal characters")
    elif module_type == "check":
        if bool(data.get("file")) == bool(data.get("command")):
            raise ModuleError(f"{location} requires exactly one of file or command")
        if data.get("file"):
            spec = data["file"]
            if not isinstance(spec, dict) or set(spec) - {"path", "exists", "sha256"}:
                raise ModuleError(f"{location}.file contains an unknown field")
            _required_str(spec, "path", f"{location}.file")
            if type(spec.get("exists", True)) is not bool:
                raise ModuleError(f"{location}.file.exists must be boolean")
            sha = _optional_str(spec, "sha256", f"{location}.file")
            if sha and __import__("re").fullmatch(r"[0-9a-fA-F]{64}", sha) is None:
                raise ModuleError(f"{location}.file.sha256 must be 64 hexadecimal characters")
        if data.get("command"):
            spec = data["command"]
            if not isinstance(spec, dict) or set(spec) - {"run", "exitCode"}:
                raise ModuleError(f"{location}.command contains an unknown field")
            _required_str(spec, "run", f"{location}.command")
            if type(spec.get("exitCode", 0)) is not int or not 0 <= spec.get("exitCode", 0) <= 255:
                raise ModuleError(f"{location}.command.exitCode must be 0..255")
    elif module_type == "dll":
        if not data.get("install") and not data.get("overrides"):
            raise ModuleError(f"{location} requires install or overrides")
        if data.get("install"):
            spec = data["install"]
            if not isinstance(spec, dict) or set(spec) != {"source", "target", "sha256"}:
                raise ModuleError(f"{location}.install requires source, target and sha256")
            _required_str(spec, "source", f"{location}.install")
            if spec["target"] not in {"system32", "syswow64"}:
                raise ModuleError(f"{location}.install.target must be system32 or syswow64")
            if not isinstance(spec["sha256"], str) or not __import__("re").fullmatch(r"[0-9a-fA-F]{64}", spec["sha256"]):
                raise ModuleError(f"{location}.install.sha256 must be 64 hexadecimal characters")
        if data.get("overrides"):
            overrides = data["overrides"]
            if not isinstance(overrides, dict) or not overrides or any(
                not isinstance(name, str) or not __import__("re").fullmatch(r"[A-Za-z0-9_.-]+", name)
                or policy not in {"native", "builtin", "native,builtin", "builtin,native", "disabled"}
                for name, policy in overrides.items()):
                raise ModuleError(f"{location}.overrides contains an invalid DLL policy")
            names = [name.lower().removesuffix(".dll") for name in overrides]
            if len(names) != len(set(names)) or "" in names:
                raise ModuleError(f"{location}.overrides contains duplicate normalized DLL names")
        if "evidence" in data and (not isinstance(data["evidence"], dict) or set(data["evidence"]) - {"id", "failure", "artifact", "runtime"} or any(not isinstance(v, str) for v in data["evidence"].values())):
            raise ModuleError(f"{location}.evidence must contain string id/failure/artifact/runtime fields")
    elif module_type == "winetricks" and data.get("verbs") is not None:
        _string_list(data["verbs"], f"{location}.verbs")
    elif module_type == "portable":
        _optional_str(data, "source", location)
        _optional_str(data, "target", location)
    elif module_type == "files" and data.get("mappings") is not None:
        _validate_files_mappings(data["mappings"], location)
    elif module_type == "script":
        for name in ("run", "file", "shell"):
            _optional_str(data, name, location)
        if sum(bool(data.get(name)) for name in ("run", "file")) != 1:
            raise ModuleError(f"{location} requires exactly one of run or file")
        sha = _optional_str(data, "sha256", location)
        if sha and (not data.get("file") or __import__("re").fullmatch(r"[0-9a-fA-F]{64}", sha) is None):
            raise ModuleError(f"{location}.sha256 requires a file and 64 hexadecimal characters")
        if data.get("shell", "/bin/bash") not in {"/bin/bash", "/bin/sh"}:
            raise ModuleError(f"{location}.shell must be /bin/bash or /bin/sh")
        if data.get("user", "root") != "root":
            raise ModuleError(f"{location}.user only supports root build context")
        if "timeout" in data and (type(data["timeout"]) is not int or data["timeout"] <= 0):
            raise ModuleError(f"{location}.timeout must be a positive integer")
        if "environment" in data and (not isinstance(data["environment"], dict) or
            any(not isinstance(k, str) or not __import__("re").fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) or not isinstance(v, str)
                for k, v in data["environment"].items())):
            raise ModuleError(f"{location}.environment must map variable names to strings")
        outputs = data.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            raise ModuleError(f"{location}.outputs must declare Linux artifact paths to preserve")
        from .paths import validate_linux_output
        for path in _string_list(outputs, f"{location}.outputs"):
            validate_linux_output(path)
        _optional_str(data, "workingDirectory", location)
    elif module_type == "chocolatey":
        install = data.get("install")
        if install is not None and not isinstance(install, dict):
            raise ModuleError(f"{location}.install must be an object")
        if data.get("packages") is not None and install is not None and "packages" in install:
            raise ModuleError(f"{location} cannot combine packages with install.packages")
        _optional_str(data, "packageSource", location)



def parse_module(data: dict[str, Any], index: int = 0) -> ModuleBase:
    """Parse a module definition from a dict.
    
    This function takes a dictionary representing a module definition
    and returns the appropriate ModuleBase subclass instance.
    
    Args:
        data: Module definition dict with 'type' field
        index: Module index for error messages
    
    Returns:
        Appropriate ModuleBase subclass instance
    
    Raises:
        ModuleError: If module type is unknown or required fields are missing
    """
    from .chocolatey import ChocolateyModule
    from .iso import IsoModule
    from .winetricks import WinetricksModule
    from .portable import PortableModule
    from .files import FilesModule
    from .script import ScriptModule
    from .install import InstallModule
    from .registry import RegistryModule
    from .extract import ExtractModule
    from .check import CheckModule
    from .dll import DllModule

    if not isinstance(data, dict):
        raise ModuleError(f"modules[{index}] must be an object")

    module_type = data.get("type")
    if not isinstance(module_type, str) or not module_type.strip():
        raise ModuleError(f"modules[{index}] missing 'type' field")
    
    # Extract defaults if present
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ModuleError(f"modules[{index}] 'defaults' must be a dict")
    
    # Merge defaults with user data
    merged_data = ModuleBase(type=module_type, defaults=defaults).merge_defaults(data)
    if module_type not in MODULE_FIELDS:
        raise ModuleError(f"modules[{index}] unknown module type: {module_type}")
    _validate_common_module_data(module_type, merged_data, index)
    
    # Parse based on module type
    if module_type == "chocolatey":
        module = ChocolateyModule(
            type=module_type,
            defaults=defaults,
            install=merged_data.get("install"),
            packages=merged_data.get("packages"),
            package_source=merged_data.get("packageSource"),
        )
        module.validate()
        return module
    elif module_type == "install":
        module = InstallModule(type=module_type, defaults=defaults,
            source=merged_data["source"], installer=merged_data.get("installer"),
            sha256=merged_data.get("sha256"), args=merged_data.get("args"),
            working_directory=merged_data.get("workingDirectory"),
            environment=merged_data.get("environment"), timeout=merged_data.get("timeout"),
            expected_exit_codes=merged_data.get("expectedExitCodes"))
        module.mechanism()
        return module
    elif module_type == "registry":
        return RegistryModule(type=module_type, defaults=defaults, file=merged_data.get("file"),
            changes=merged_data.get("changes"), sha256=merged_data.get("sha256"),
            view=merged_data.get("view", "default"), user=merged_data.get("user", "application"))
    elif module_type == "extract":
        return ExtractModule(type=module_type, defaults=defaults, source=merged_data.get("source"),
            target=merged_data.get("target"), sha256=merged_data.get("sha256"),
            max_bytes=merged_data.get("maxBytes", 2 * 1024**3), backend=merged_data.get("backend"))
    elif module_type == "check":
        return CheckModule(type=module_type, defaults=defaults,
            file=merged_data.get("file"), command=merged_data.get("command"))
    elif module_type == "dll":
        return DllModule(type=module_type, defaults=defaults,
            install=merged_data.get("install"), overrides=merged_data.get("overrides"),
            evidence=merged_data.get("evidence"))
    elif module_type == "iso":
        return IsoModule(
            type=module_type,
            defaults=defaults,
            action=merged_data.get("action", "mount"), id=merged_data.get("id"),
            source=merged_data.get("source"),
            drive=merged_data.get("drive"), backend=merged_data.get("backend", "host"),
            mount_path=merged_data.get("mountPath"), sha256=merged_data.get("sha256"),
        )
    elif module_type == "winetricks":
        return WinetricksModule(
            type=module_type,
            defaults=defaults,
            verbs=merged_data.get("verbs"),
        )
    elif module_type == "portable":
        return PortableModule(
            type=module_type,
            defaults=defaults,
            source=merged_data.get("source"),
            target=merged_data.get("target"),
        )
    elif module_type == "files":
        return FilesModule(
            type=module_type,
            defaults=defaults,
            mappings=merged_data.get("mappings"),
        )
    elif module_type == "script":
        working_directory = merged_data.get("workingDirectory")
        return ScriptModule(
            type=module_type,
            defaults=defaults,
            working_directory=working_directory,
            run=merged_data.get("run"), file=merged_data.get("file"),
            sha256=merged_data.get("sha256"),
            shell=merged_data.get("shell", "/bin/bash"),
            environment=merged_data.get("environment"), timeout=merged_data.get("timeout"),
            user=merged_data.get("user", "root"), outputs=merged_data.get("outputs"),
        )
    else:
        raise ModuleError(f"modules[{index}] unknown module type: {module_type}")


__all__ = [
    "ModuleError",
    "ModuleBase",
    "parse_module",
]
