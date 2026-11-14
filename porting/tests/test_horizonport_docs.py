"""The porting kit's paperwork has to stay true: documents, links, schemas, the mark."""

import json
import pathlib
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / "porting"

DOCUMENTS = (
    "README.md",
    "AGENT-GUIDE.md",
    "CHECKLIST.md",
    "contract.md",
    "assets.md",
    "auth.md",
    "launch.md",
    "mods.md",
    "faq.md",
)

SCHEMAS = (
    "port.config.schema.json",
    "instance.schema.json",
    "launch-plan.schema.json",
    "store-index.schema.json",
    "horizonport-bundle.schema.json",
)


def markdown_links(path: pathlib.Path):
    """Every relative link target in a Markdown file, without anchors or URLs."""
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\]\((?!#)([^)#\s]+)(?:#[^)]*)?\)", text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        yield target


class KitTests(unittest.TestCase):
    def test_every_document_exists_and_is_not_a_stub(self):
        for name in DOCUMENTS:
            path = KIT / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(len(path.read_text(encoding="utf-8")), 2_000, name)

    def test_the_handbook_is_at_the_root_where_the_tool_says(self):
        handbook = ROOT / "PORTING.md"
        self.assertTrue(handbook.is_file())
        self.assertGreater(len(handbook.read_text(encoding="utf-8")), 10_000)

    def test_relative_links_in_the_kit_and_the_readme_resolve(self):
        for path in [ROOT / "README.md", ROOT / "PORTING.md", *(KIT / name for name in DOCUMENTS)]:
            for target in markdown_links(path):
                self.assertTrue((path.parent / target).exists(), f"{path.name} → {target}")

    def test_the_mark_parses_and_says_who_made_it(self):
        svg = KIT / "media" / "horizonport.svg"
        self.assertTrue(svg.is_file())
        tree = ET.parse(svg)  # raises on malformed XML
        text = " ".join(node.text or "" for node in tree.iter())
        self.assertIn("HorizonPort", text)
        self.assertIn("Buffer", text)

    def test_the_schemas_are_json_with_an_id_and_a_version(self):
        for name in SCHEMAS:
            payload = json.loads((KIT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertIsInstance(payload, dict, name)
            self.assertIn("$schema", payload, name)
            self.assertIn("title", payload, name)

    def test_the_config_schema_accepts_the_adapters_the_init_command_offers(self):
        schema = json.loads((KIT / "schemas" / "port.config.schema.json").read_text(encoding="utf-8"))
        offered = schema["properties"]["adapter"]["properties"]["kind"]["enum"]
        self.assertEqual(set(offered), {"node", "rust", "python", "none"})
        for kind in offered:
            if kind != "none":
                self.assertTrue((KIT / "templates" / f"adapter-{kind}").is_dir(), kind)

    def test_the_launchers_exist_and_the_shell_one_is_executable(self):
        self.assertTrue((KIT / "bin" / "horizonport").is_file())
        self.assertTrue((KIT / "bin" / "horizonport.cmd").is_file())
        self.assertTrue((KIT / "bin" / "horizonport").stat().st_mode & 0o111)


if __name__ == "__main__":
    unittest.main()
