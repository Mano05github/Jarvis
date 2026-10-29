from __future__ import annotations

import hashlib
import json
import math
import os
import posixpath
import struct
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "deliverables"
ARCHITECTURE_OUT = OUT / "architecture"
PLANS_OUT = OUT / "plans"
MANIFESTS_OUT = OUT / "manifests"
for directory in (OUT, ARCHITECTURE_OUT, PLANS_OUT, MANIFESTS_OUT):
    directory.mkdir(parents=True, exist_ok=True)

DOCX_PATH = ARCHITECTURE_OUT / "Jarvis_Architecture_and_Implementation_Plan.docx"
XLSX_PATH = PLANS_OUT / "Jarvis_Implementation_Sprint_Plan_v2.xlsx"
MANIFEST_PATH = MANIFESTS_OUT / "deliverables_manifest.json"
IMAGE_PORTRAIT = ROOT / "assets" / "character-references" / "portrait.jpg"
IMAGE_TURNAROUND = ROOT / "assets" / "character-references" / "turnaround.jpg"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
DCTERMS = "http://purl.org/dc/terms/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"

for prefix, uri in [("w", W), ("r", R), ("wp", WP), ("a", A), ("pic", PIC),
                    ("cp", CP), ("dc", DC), ("dcterms", DCTERMS), ("xsi", XSI)]:
    ET.register_namespace(prefix, uri)


def qn(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def xml_bytes(element: ET.Element) -> bytes:
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError(f"Not a JPEG: {path}")
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xD8, 0xD9):
            continue
        length = struct.unpack(">H", data[i:i + 2])[0]
        if marker in range(0xC0, 0xC4):
            h, w = struct.unpack(">HH", data[i + 3:i + 7])
            return w, h
        i += length
    raise ValueError(f"JPEG size not found: {path}")


class DocxBuilder:
    def __init__(self) -> None:
        self.document = ET.Element(qn(W, "document"))
        self.body = ET.SubElement(self.document, qn(W, "body"))
        self.relationships: list[tuple[str, str, str]] = []
        self.image_count = 0
        self.docpr_id = 1

    def add_relationship(self, rel_type: str, target: str) -> str:
        rid = f"rId{len(self.relationships) + 1}"
        self.relationships.append((rid, rel_type, target))
        return rid

    def paragraph(self, text: str = "", style: str | None = None, *,
                  bold: bool = False, italic: bool = False, color: str | None = None,
                  align: str | None = None, before: int | None = None,
                  after: int | None = None, keep_next: bool = False) -> ET.Element:
        p = ET.SubElement(self.body, qn(W, "p"))
        ppr = ET.SubElement(p, qn(W, "pPr"))
        if style:
            ET.SubElement(ppr, qn(W, "pStyle"), {qn(W, "val"): style})
        if keep_next:
            ET.SubElement(ppr, qn(W, "keepNext"))
        if before is not None or after is not None:
            attrs = {}
            if before is not None:
                attrs[qn(W, "before")] = str(before)
            if after is not None:
                attrs[qn(W, "after")] = str(after)
            ET.SubElement(ppr, qn(W, "spacing"), attrs)
        if align:
            ET.SubElement(ppr, qn(W, "jc"), {qn(W, "val"): align})
        if text:
            self.run(p, text, bold=bold, italic=italic, color=color)
        return p

    def run(self, p: ET.Element, text: str, *, bold: bool = False,
            italic: bool = False, color: str | None = None, font: str | None = None,
            size: int | None = None) -> ET.Element:
        r = ET.SubElement(p, qn(W, "r"))
        rpr = ET.SubElement(r, qn(W, "rPr"))
        if font:
            ET.SubElement(rpr, qn(W, "rFonts"), {
                qn(W, "ascii"): font, qn(W, "hAnsi"): font, qn(W, "cs"): font})
        if bold:
            ET.SubElement(rpr, qn(W, "b"))
        if italic:
            ET.SubElement(rpr, qn(W, "i"))
        if color:
            ET.SubElement(rpr, qn(W, "color"), {qn(W, "val"): color})
        if size:
            ET.SubElement(rpr, qn(W, "sz"), {qn(W, "val"): str(size)})
            ET.SubElement(rpr, qn(W, "szCs"), {qn(W, "val"): str(size)})
        t = ET.SubElement(r, qn(W, "t"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
        t.text = text
        return r

    def heading(self, text: str, level: int = 1) -> ET.Element:
        return self.paragraph(text, f"Heading{level}", keep_next=True)

    def bullet(self, text: str, level: int = 0) -> ET.Element:
        return self.paragraph("• " + text, "ListBullet" if level == 0 else "ListBullet2")

    def numbered(self, number: str, text: str) -> ET.Element:
        p = self.paragraph(style="ListNumber")
        self.run(p, f"{number}. ", bold=True, color="16324F")
        self.run(p, text)
        return p

    def code(self, text: str) -> ET.Element:
        p = self.paragraph(style="CodeBlock")
        for idx, line in enumerate(text.splitlines()):
            if idx:
                ET.SubElement(p, qn(W, "r"))
                r = p[-1]
                ET.SubElement(r, qn(W, "br"))
            self.run(p, line, font="Consolas", size=18)
        return p

    def page_break(self) -> None:
        p = self.paragraph()
        r = ET.SubElement(p, qn(W, "r"))
        ET.SubElement(r, qn(W, "br"), {qn(W, "type"): "page"})

    def table(self, headers: list[str], rows: list[list[object]], widths: list[int] | None = None) -> ET.Element:
        tbl = ET.SubElement(self.body, qn(W, "tbl"))
        tblpr = ET.SubElement(tbl, qn(W, "tblPr"))
        ET.SubElement(tblpr, qn(W, "tblStyle"), {qn(W, "val"): "TableGrid"})
        ET.SubElement(tblpr, qn(W, "tblW"), {qn(W, "w"): "0", qn(W, "type"): "auto"})
        ET.SubElement(tblpr, qn(W, "tblLook"), {qn(W, "val"): "04A0"})
        grid = ET.SubElement(tbl, qn(W, "tblGrid"))
        for cidx in range(len(headers)):
            width = widths[cidx] if widths and cidx < len(widths) else int(9000 / max(1, len(headers)))
            ET.SubElement(grid, qn(W, "gridCol"), {qn(W, "w"): str(width)})
        all_rows = [headers] + [[str(v) for v in row] for row in rows]
        for ridx, row in enumerate(all_rows):
            tr = ET.SubElement(tbl, qn(W, "tr"))
            if ridx == 0:
                trpr = ET.SubElement(tr, qn(W, "trPr"))
                ET.SubElement(trpr, qn(W, "tblHeader"))
            for cidx, value in enumerate(row):
                tc = ET.SubElement(tr, qn(W, "tc"))
                tcpr = ET.SubElement(tc, qn(W, "tcPr"))
                if widths and cidx < len(widths):
                    ET.SubElement(tcpr, qn(W, "tcW"), {qn(W, "w"): str(widths[cidx]), qn(W, "type"): "dxa"})
                if ridx == 0:
                    ET.SubElement(tcpr, qn(W, "shd"), {qn(W, "val"): "clear", qn(W, "fill"): "16324F"})
                elif ridx % 2 == 0:
                    ET.SubElement(tcpr, qn(W, "shd"), {qn(W, "val"): "clear", qn(W, "fill"): "EEF3F7"})
                p = ET.SubElement(tc, qn(W, "p"))
                ppr = ET.SubElement(p, qn(W, "pPr"))
                ET.SubElement(ppr, qn(W, "spacing"), {qn(W, "after"): "40"})
                self.run(p, value, bold=(ridx == 0), color=("FFFFFF" if ridx == 0 else None), size=18)
        return tbl

    def image(self, path: Path, width_inches: float, caption: str) -> None:
        self.image_count += 1
        target = f"media/image{self.image_count}.jpg"
        rid = self.add_relationship(
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image", target)
        px_w, px_h = jpeg_size(path)
        cx = int(width_inches * 914400)
        cy = int(cx * px_h / px_w)
        p = self.paragraph(align="center")
        r = ET.SubElement(p, qn(W, "r"))
        drawing = ET.SubElement(r, qn(W, "drawing"))
        inline = ET.SubElement(drawing, qn(WP, "inline"), {
            "distT": "0", "distB": "0", "distL": "0", "distR": "0"})
        ET.SubElement(inline, qn(WP, "extent"), {"cx": str(cx), "cy": str(cy)})
        ET.SubElement(inline, qn(WP, "effectExtent"), {"l": "0", "t": "0", "r": "0", "b": "0"})
        ET.SubElement(inline, qn(WP, "docPr"), {"id": str(self.docpr_id), "name": path.name})
        self.docpr_id += 1
        frame = ET.SubElement(inline, qn(WP, "cNvGraphicFramePr"))
        ET.SubElement(frame, qn(A, "graphicFrameLocks"), {"noChangeAspect": "1"})
        graphic = ET.SubElement(inline, qn(A, "graphic"))
        gd = ET.SubElement(graphic, qn(A, "graphicData"), {"uri": "http://schemas.openxmlformats.org/drawingml/2006/picture"})
        pic = ET.SubElement(gd, qn(PIC, "pic"))
        nv = ET.SubElement(pic, qn(PIC, "nvPicPr"))
        ET.SubElement(nv, qn(PIC, "cNvPr"), {"id": "0", "name": path.name})
        ET.SubElement(nv, qn(PIC, "cNvPicPr"))
        bf = ET.SubElement(pic, qn(PIC, "blipFill"))
        ET.SubElement(bf, qn(A, "blip"), {qn(R, "embed"): rid})
        stretch = ET.SubElement(bf, qn(A, "stretch"))
        ET.SubElement(stretch, qn(A, "fillRect"))
        sp = ET.SubElement(pic, qn(PIC, "spPr"))
        xfrm = ET.SubElement(sp, qn(A, "xfrm"))
        ET.SubElement(xfrm, qn(A, "off"), {"x": "0", "y": "0"})
        ET.SubElement(xfrm, qn(A, "ext"), {"cx": str(cx), "cy": str(cy)})
        geom = ET.SubElement(sp, qn(A, "prstGeom"), {"prst": "rect"})
        ET.SubElement(geom, qn(A, "avLst"))
        self.paragraph(caption, "Caption", italic=True, align="center")

    def toc(self) -> None:
        p = self.paragraph()
        r1 = ET.SubElement(p, qn(W, "r"))
        ET.SubElement(r1, qn(W, "fldChar"), {qn(W, "fldCharType"): "begin", qn(W, "dirty"): "true"})
        r2 = ET.SubElement(p, qn(W, "r"))
        instr = ET.SubElement(r2, qn(W, "instrText"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
        instr.text = ' TOC \\o "1-3" \\h \\z \\u '
        r3 = ET.SubElement(p, qn(W, "r"))
        ET.SubElement(r3, qn(W, "fldChar"), {qn(W, "fldCharType"): "separate"})
        self.run(p, "Update this field in Word to generate page numbers.", italic=True, color="607080")
        r4 = ET.SubElement(p, qn(W, "r"))
        ET.SubElement(r4, qn(W, "fldChar"), {qn(W, "fldCharType"): "end"})

    def finish(self, footer_rid: str) -> None:
        sect = ET.SubElement(self.body, qn(W, "sectPr"))
        ET.SubElement(sect, qn(W, "footerReference"), {qn(W, "type"): "default", qn(R, "id"): footer_rid})
        ET.SubElement(sect, qn(W, "pgSz"), {qn(W, "w"): "11906", qn(W, "h"): "16838"})
        ET.SubElement(sect, qn(W, "pgMar"), {
            qn(W, "top"): "1134", qn(W, "right"): "1134", qn(W, "bottom"): "1134",
            qn(W, "left"): "1134", qn(W, "header"): "600", qn(W, "footer"): "600", qn(W, "gutter"): "0"})


def styles_xml() -> bytes:
    styles = ET.Element(qn(W, "styles"))
    doc_defaults = ET.SubElement(styles, qn(W, "docDefaults"))
    rpr_def = ET.SubElement(ET.SubElement(doc_defaults, qn(W, "rPrDefault")), qn(W, "rPr"))
    ET.SubElement(rpr_def, qn(W, "rFonts"), {qn(W, "ascii"): "Aptos", qn(W, "hAnsi"): "Aptos", qn(W, "cs"): "Aptos"})
    ET.SubElement(rpr_def, qn(W, "sz"), {qn(W, "val"): "21"})
    ppr_def = ET.SubElement(ET.SubElement(doc_defaults, qn(W, "pPrDefault")), qn(W, "pPr"))
    ET.SubElement(ppr_def, qn(W, "spacing"), {qn(W, "after"): "120", qn(W, "line"): "276", qn(W, "lineRule"): "auto"})

    def style(style_id: str, name: str, *, based: str | None = None, size: int | None = None,
              bold: bool = False, color: str | None = None, before: int = 0, after: int = 80,
              outline: int | None = None, font: str | None = None, italic: bool = False,
              left: int | None = None, first: int | None = None, fill: str | None = None) -> None:
        s = ET.SubElement(styles, qn(W, "style"), {qn(W, "type"): "paragraph", qn(W, "styleId"): style_id})
        ET.SubElement(s, qn(W, "name"), {qn(W, "val"): name})
        if based:
            ET.SubElement(s, qn(W, "basedOn"), {qn(W, "val"): based})
        ppr = ET.SubElement(s, qn(W, "pPr"))
        if outline is not None:
            ET.SubElement(ppr, qn(W, "keepNext"))
        if fill:
            ET.SubElement(ppr, qn(W, "shd"), {qn(W, "val"): "clear", qn(W, "fill"): fill})
        ET.SubElement(ppr, qn(W, "spacing"), {qn(W, "before"): str(before), qn(W, "after"): str(after)})
        if left is not None:
            attrs = {qn(W, "left"): str(left)}
            if first is not None:
                attrs[qn(W, "hanging")] = str(first)
            ET.SubElement(ppr, qn(W, "ind"), attrs)
        elif fill:
            ET.SubElement(ppr, qn(W, "ind"), {qn(W, "left"): "180", qn(W, "right"): "180"})
        if outline is not None:
            ET.SubElement(ppr, qn(W, "outlineLvl"), {qn(W, "val"): str(outline)})
        rpr = ET.SubElement(s, qn(W, "rPr"))
        if font:
            ET.SubElement(rpr, qn(W, "rFonts"), {qn(W, "ascii"): font, qn(W, "hAnsi"): font})
        if bold:
            ET.SubElement(rpr, qn(W, "b"))
        if italic:
            ET.SubElement(rpr, qn(W, "i"))
        if color:
            ET.SubElement(rpr, qn(W, "color"), {qn(W, "val"): color})
        if size:
            ET.SubElement(rpr, qn(W, "sz"), {qn(W, "val"): str(size)})
            ET.SubElement(rpr, qn(W, "szCs"), {qn(W, "val"): str(size)})

    style("Normal", "Normal")
    style("Title", "Title", size=48, bold=True, color="16324F", after=240)
    style("Subtitle", "Subtitle", size=26, color="3C6E71", after=180)
    style("Heading1", "heading 1", based="Normal", size=34, bold=True, color="16324F", before=280, after=120, outline=0)
    style("Heading2", "heading 2", based="Normal", size=28, bold=True, color="2A5D67", before=220, after=100, outline=1)
    style("Heading3", "heading 3", based="Normal", size=23, bold=True, color="8C3B3B", before=160, after=80, outline=2)
    style("ListBullet", "List Bullet", based="Normal", left=420, first=240)
    style("ListBullet2", "List Bullet 2", based="Normal", left=780, first=240)
    style("ListNumber", "List Number", based="Normal", left=360)
    style("CodeBlock", "Code Block", based="Normal", font="Consolas", size=18, fill="EEF3F7", before=80, after=120)
    style("Caption", "Caption", based="Normal", size=18, italic=True, color="5A6872", after=140)

    ts = ET.SubElement(styles, qn(W, "style"), {qn(W, "type"): "table", qn(W, "styleId"): "TableGrid"})
    ET.SubElement(ts, qn(W, "name"), {qn(W, "val"): "Table Grid"})
    return xml_bytes(styles)


def footer_xml() -> bytes:
    footer = ET.Element(qn(W, "ftr"))
    p = ET.SubElement(footer, qn(W, "p"))
    ppr = ET.SubElement(p, qn(W, "pPr"))
    ET.SubElement(ppr, qn(W, "jc"), {qn(W, "val"): "center"})
    r = ET.SubElement(p, qn(W, "r"))
    t = ET.SubElement(r, qn(W, "t"))
    t.text = "Jarvis Architecture • Confidential • Page "
    rb = ET.SubElement(p, qn(W, "r"))
    ET.SubElement(rb, qn(W, "fldChar"), {qn(W, "fldCharType"): "begin"})
    ri = ET.SubElement(p, qn(W, "r"))
    instr = ET.SubElement(ri, qn(W, "instrText"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
    instr.text = " PAGE "
    re = ET.SubElement(p, qn(W, "r"))
    ET.SubElement(re, qn(W, "fldChar"), {qn(W, "fldCharType"): "end"})
    return xml_bytes(footer)


def add_narrative(doc: DocxBuilder, paragraphs: list[str]) -> None:
    for text in paragraphs:
        doc.paragraph(text)


def build_docx() -> None:
    d = DocxBuilder()
    d.add_relationship(
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "styles.xml")
    footer_rid = d.add_relationship(
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer", "footer1.xml")

    # Cover
    d.paragraph("JARVIS", "Title", align="center", before=600)
    d.paragraph("Personal AI Companion and Windows Agent", "Subtitle", align="center")
    d.paragraph("Reference Architecture, Algorithms, Tool Harness, Guardrails and Final Implementation Plan",
                "Subtitle", align="center")
    if IMAGE_PORTRAIT.exists():
        d.image(IMAGE_PORTRAIT, 2.7, "Canonical character concept — front walking view")
    d.paragraph("Architecture baseline v1.7", align="center", bold=True, color="16324F", before=180)
    d.paragraph("Updated 12 October 2026 • Windows-first • Local-privacy-first", align="center", color="607080")
    d.page_break()

    d.heading("Document purpose and status", 1)
    add_narrative(d, [
        "This document freezes the first production architecture for Jarvis: an embodied, conversational, privacy-controlled personal AI capable of observing permitted Windows context and executing authorized work through governed tools. It consolidates the design decisions reached during the architecture discussion and converts them into implementable components, algorithms, interfaces, security boundaries and delivery increments.",
        "The architecture is intentionally model-independent and tool-independent. Language models propose structured intentions but never become an authorization authority. All consequential effects pass through deterministic policy, narrow capabilities, isolated execution and independent verification. This principle makes it possible to expand Jarvis over time without giving an LLM, an MCP server or malicious screen content ownership of the laptop.",
        "The accompanying Excel workbook is the delivery control document. Its dates and story points are planning assumptions that should be recalibrated after Sprint 0 based on the team size, target hardware and chosen service providers."
    ])
    d.table(["Item", "Decision"], [
        ["Primary platform", "Windows 11 desktop; standard-user execution by default"],
        ["Agent runtime", "Python and LangGraph, with selected LangChain adapters"],
        ["Character", "Rigged 3D character rendered in a transparent Godot 4 overlay"],
        ["Native control", "Signed C#/.NET Windows Capability Broker"],
        ["Authorization", "OPA/Rego policy decision service plus signed capability grants"],
        ["Tool ecosystem", "MCP and native capabilities behind the Jarvis Tool Capability Platform"],
        ["Speech and Tanglish", "Offline STT produces untrusted evidence; one provider-neutral primary multilingual LLM handles open-domain Tanglish conversation, clarification and plan proposals behind typed contracts"],
        ["Target hardware", "Ryzen 5 7520U (4C/8T), 16 GB RAM, integrated Radeon graphics, Windows 11 25H2"],
        ["Python runtime", "Python 3.12.10 in D:/Projects/Jarvis/.venv"],
        ["Observability", "OpenTelemetry plus a separate append-only security audit journal"],
        ["Status", "Phase 1 foundation active; companion/planner contracts and safe provider configuration are implemented, while live-provider and end-to-end speech certification remain"],
    ], [2400, 6500])

    d.heading("Contents", 1)
    d.toc()
    d.table(["Part", "Coverage"], [
        ["1–3", "Introduction, final system architecture, hardware profile and separate STT/semantic-decoder/TTS architectures"],
        ["4–6", "Runtime flows, deep logic/algorithms and effective engineering strategies"],
        ["7", "Separate Tool Capability Platform and MCP harness architecture"],
        ["8", "Separate guardrail, policy and Windows containment architecture"],
        ["9–11", "Character, telemetry/audit, memory and data architecture"],
        ["12–15", "Testing, implementation plan, acceptance criteria and appendices"],
    ], [1300, 7600])
    d.page_break()

    # 1 Introduction
    d.heading("1. Introduction", 1)
    d.heading("1.1 Vision", 2)
    add_narrative(d, [
        "Jarvis is not a chatbot with a desktop skin. It is a long-running personal agent made of three deliberately separated products: an embodied companion, a cognitive assistant and a computer operator. The character creates social presence; the cognitive plane interprets goals and plans; the capability plane performs bounded work. The user experiences one coherent personality while the implementation preserves strict trust boundaries.",
        "The intended experience is a character that can live in a reserved zone above the taskbar, walk or run across configured screen regions, speak naturally, listen with interruption support, watch permitted media with the user, remember approved preferences, offer timely assistance and operate Windows applications. It must also become blind in user-defined private zones and explain every consequential action."
    ])
    d.heading("1.2 Primary objectives", 2)
    for x in [
        "Provide low-latency voice and text conversation with a persistent, consistent personality.",
        "Maintain contextual awareness using metadata and Windows UI Automation before screenshots.",
        "Perform useful Windows, browser, file, document and development tasks through verified capabilities.",
        "Give the user separate control over what Jarvis may see, use temporarily and remember.",
        "Harness a growing MCP ecosystem without trusting MCP as a security boundary.",
        "Record comprehensible operational traces and authoritative action history for later review.",
        "Improve safely through reviewed workflows, measured tool outcomes and staged autonomy."
    ]:
        d.bullet(x)
    d.heading("1.3 Explicit non-goals", 2)
    for x in [
        "Movie-level artificial general intelligence or unlimited self-directed autonomy.",
        "Permanent recording of the desktop, microphone or camera.",
        "A generic elevated shell, unrestricted PowerShell or arbitrary command execution.",
        "Silent impersonation, hidden surveillance, credential extraction or approval on behalf of the user.",
        "Automatic installation of tools suggested by a model or content encountered on the web.",
        "Self-modifying policy or unreviewed deployment of generated code."
    ]:
        d.bullet(x)

    # 2 Observations
    d.heading("2. Consolidated observations and requirements", 1)
    d.heading("2.1 Character observations", 2)
    add_narrative(d, [
        "The supplied character references define an adult South Asian man with thick curly black hair, a full beard and moustache, dark sunglasses, a red/navy plaid short-sleeve shirt, dark trousers, brown shoes, a cross-body messenger bag, a red ID lanyard and white wired earphones. The posture is relaxed and confident, commonly with hands in pockets. The walking illustration establishes attitude and movement; the turnaround sheet establishes front, left, back and right silhouettes plus accessory, palette and material details.",
        "The turnaround is a concept reference rather than a production mesh. A finished asset still requires eye design behind the sunglasses, facial topology, mouth blend shapes, a humanoid skeleton, hand poses, cloth-aware deformation and secondary-motion rigs for hair, bag, lanyard and cables. At taskbar scale the silhouette, hair, sunglasses, plaid massing and bag must remain recognizable even when small details are simplified."
    ])
    if IMAGE_TURNAROUND.exists():
        d.image(IMAGE_TURNAROUND, 6.8, "Canonical turnaround and detail reference used by the 3D asset pipeline")
    d.heading("2.2 Functional requirements", 2)
    d.table(["Domain", "Required behavior"], [
        ["Interaction", "Wake word, push-to-talk, chat input, streaming response, barge-in and sleep/private modes"],
        ["Companion", "Idle, walk, run, listen, speak, react, watch permitted media and express bounded emotion"],
        ["Perception", "Active app/window metadata, UIA structure, scoped screenshot/OCR fallback and provenance"],
        ["Computer use", "Open/focus applications, safe UI operations, files, browser, media and approved workflows"],
        ["Memory", "Working, episodic, semantic and procedural memory with consent, provenance and deletion"],
        ["Proactivity", "Deterministic triggers, quiet hours, relevance thresholds, cooldowns and visible reasons"],
        ["Governance", "Risk classification, approvals, policy enforcement, verification, rollback and emergency stop"],
        ["Review", "Trace every task and preserve authoritative, privacy-filtered action records"],
    ], [1900, 7000])
    d.heading("2.3 Non-functional requirements", 2)
    for x in [
        "Local-first privacy: classification and redaction happen before remote model calls.",
        "Least privilege: every process, secret, filesystem root, network destination and action is narrowly scoped.",
        "Determinism at security boundaries: policy, validation, approval and verification are code, not prompts.",
        "Crash safety: checkpoints and idempotency prevent an interrupted workflow from repeating external effects.",
        "User interruptibility: keyboard/mouse takeover, tray pause and a global emergency hotkey stop actuation.",
        "Explainability: Jarvis can state why it observed context, selected a tool, requested approval or stopped.",
        "Replaceability: model providers and MCP implementations can change without redesigning the core."
    ]:
        d.bullet(x)

    # 3 Architecture
    d.heading("3. Reference system architecture", 1)
    d.heading("3.1 Architectural overview", 2)
    d.code("USER / VOICE / CHARACTER\n"
           "          │\n"
           "          ▼\n"
           "INTERACTION: VAD -> STT evidence -> acoustic/evidence quality gate\n"
           "          │\n"
           "          ▼\n"
           "PRIMARY MULTILINGUAL LLM GATEWAY -> chat | clarify | typed plan\n"
           "          │\n"
           "          ▼\n"
           "LANGGRAPH + PRIMARY LLM PLANNER <-> LOCAL PRIVACY FIREWALL\n"
           "          │  proposed ActionIntent / plan\n"
           "          ▼\n"
           "POLICY GATEWAY (PEP) -> OPA (PDP) <- PIP / APPROVAL UI\n"
           "          │  signed capability grant\n"
           "      ┌───┴────────────┐\n"
           "      ▼                ▼\n"
           "MCP TOOL RUNTIME  C# WINDOWS BROKER\n"
           "      └───┬────────────┘\n"
           "          ▼\n"
           "INDEPENDENT VERIFIER -> MEMORY / AUDIT / OPENTELEMETRY")
    add_narrative(d, [
        "The architecture uses five planes. The experience plane contains the character and trusted UI. The cognitive plane contains the provider-neutral multilingual companion/planner gateway and bounded orchestration. The control plane contains evidence validation, privacy, plan validation, policy, approvals and capability issuance. The capability plane contains isolated MCP servers and the native Windows broker. The evidence plane contains verification, audit, memory provenance and OpenTelemetry. No single compromise crosses all five planes without encountering a deterministic boundary.",
        "The trusted approval window must be technically distinct from the animated character. A compromised avatar or rendered webpage must not be able to counterfeit approval. The policy gateway accepts approval only as a signed, expiring event from the trusted UI; for high-impact operations it can additionally require Windows Hello."
    ])
    d.heading("3.2 Component responsibilities", 2)
    d.table(["Component", "Responsibility", "Trust posture"], [
        ["Godot character", "Presentation, state, animation, subtitles and non-authoritative prompts", "Untrusted for approval"],
        ["Interaction service", "Wake word, VAD, STT, TTS, barge-in and turn management", "Local sensor boundary"],
        ["Primary LLM gateway", "Understand open-domain Tanglish, converse, clarify and propose typed plans through swappable remote/local providers", "Untrusted proposer; no authority"],
        ["Plan validator/router", "Validate schema, dependencies, references and data labels; route chat, clarification or proposed work", "Trusted deterministic control"],
        ["Perception service", "UIA, app/window events, screenshots/OCR on demand", "Minimum-context producer"],
        ["Privacy firewall", "Exclusions, labels, masking, release and retention decisions", "Trusted deterministic control"],
        ["LangGraph", "Complex-goal orchestration, subgraphs, recovery and checkpoints", "Proposes; never authorizes"],
        ["Provider adapters", "Azure OpenAI, OpenAI, Anthropic and loopback OpenAI-compatible/Ollama/llama.cpp translation", "Transport only; no direct authority"],
        ["Policy gateway", "PEP, intent validation, OPA calls, approval binding and grants", "Security authority"],
        ["Tool platform", "Catalog, retrieval, composition, runtime isolation and normalization", "Executes only grants"],
        ["Windows broker", "Narrow UIA and native Windows capabilities", "Signed native enforcement"],
        ["Verifier", "Postconditions from independent evidence", "Cannot issue authority"],
        ["Memory service", "Controlled working/episodic/semantic/procedural storage", "Provenance required"],
        ["Audit/OTel", "Security record plus operational traces, logs and metrics", "Redacted evidence plane"],
    ], [1700, 4800, 2400])
    d.heading("3.3 Deployment topology", 2)
    add_narrative(d, [
        "Core services run locally under the standard user. ACL-protected named pipes are preferred for local privileged boundaries; authenticated loopback HTTP or gRPC may be used for language-neutral services. OPA, the policy gateway, the privacy service and audit writer are local. External model calls pass through the LLM gateway. Network/document MCP servers run in ToolHive containers or an equivalent isolated runtime. Desktop automation remains native because it must access the interactive Windows session.",
        "The privileged broker is a separate executable or service with a tiny allowlisted operation set. It is not the normal Windows broker and it never offers a general terminal. Each elevated operation requires an exact signed request, one-shot user approval and native UAC/Windows Hello interaction."
    ])
    d.heading("3.4 Trust boundaries", 2)
    d.table(["Boundary", "Threat", "Enforcement"], [
        ["Screen/web → cognition", "Indirect prompt injection", "Provenance, taint labels, data/instruction separation"],
        ["STT → LLM gateway", "Acoustic deletion, hallucinated words or transcript prompt injection", "Raw evidence retention, quality metadata, privacy release and untrusted-data framing"],
        ["LLM → plan validator", "Invented entity, hidden assumption or overconfident plan", "InteractionEnvelope schema, evidence references, dependency validation and clarification state"],
        ["LLM → action", "Hallucinated or excessive action", "Schema validation, ActionIntent and OPA"],
        ["Policy → tool", "Permission reuse or expansion", "Signed grant bound to task/tool/resource/expiry"],
        ["MCP → host", "Supply-chain compromise", "Pinned digest, isolation, mounts, egress and secret brokering"],
        ["Broker → Windows", "Wrong window/element or elevation", "UIA identity checks, fresh snapshot and restricted token"],
        ["Result → memory", "Memory poisoning", "Quarantine, provenance, confidence and admission policy"],
        ["Telemetry → operator", "Sensitive-data leakage", "Redaction, field allowlists and access-controlled retention"],
    ], [2200, 2900, 3900])

    d.heading("3.5 Certified target hardware and resource policy", 2)
    add_narrative(d, [
        "The first certified target is mano_pc: Windows 11 Home Single Language 25H2, AMD Ryzen 5 7520U at 2.80 GHz with four cores and eight logical processors, 16 GB installed RAM (15.3 GB usable), LPDDR5-5500 memory, integrated AMD Radeon graphics and approximately 216 GB free on the 477 GB system volume. Virtualization is enabled. This is a capable but CPU-constrained personal-assistant platform; the integrated GPU is not treated as a dependable accelerator for model selection.",
        "Jarvis therefore uses bounded memory profiles and a single local inference scheduler. Priority order is audio capture/VAD, STT, TTS, interactive orchestration, optional local LLM work, screen/OCR work and background indexing. Heavy inference is serialized by default. Admission control checks available memory and rejects, queues or downgrades a model before Windows begins sustained pagefile thrashing.",
        "The initial character is a low-poly or otherwise optimized 3D asset with a 30 FPS foreground cap and reduced idle activity. Screen images, OCR and vision are acquired on demand rather than continuously. Qwen3-8B-Tanglish Q4_K_M is rejected on this machine: it leaves less than 0.7 GiB system memory, reaches 35-76 second p95 latency and fails the five-case semantic oracle. The replacement deterministic decoder needs no model file, passed all 14 Phase 1 packet/gate cases and measured 50.2 microseconds p95. A future task-specific classifier is optional and must earn its place on uncovered intents. Complex reasoning may use a separately approved local or remote primary endpoint only after the privacy firewall creates a permitted release view."
    ])
    d.table(["Resource", "Initial policy"], [
        ["CPU", "Reserve responsiveness for audio; bound worker threads and serialize heavyweight inference"],
        ["RAM", "Preflight every model; use hard per-service budgets and bounded buffers"],
        ["GPU", "Character rendering first; do not require GPU model acceleration"],
        ["Disk", "Store all engines, models, datasets, caches and benchmark artifacts under D:/Projects/Jarvis/storage"],
        ["Network", "Speech runs offline; remote reasoning receives only policy-approved, redacted context"],
    ], [1800, 7100])

    d.heading("3.6 Separate speech-to-text architecture", 2)
    d.code("MICROPHONE / PUSH-TO-TALK\n"
           "        -> echo cancellation + level control\n"
           "        -> local VAD + bounded pre-roll ring buffer\n"
           "        -> utterance segmenter\n"
           "        -> interchangeable local STT worker\n"
           "        -> raw transcript + alternatives + segment confidence\n"
           "        -> dual-script Tamil/English span preservation\n"
           "        -> evidence-linked entity candidates\n"
           "        -> TranscriptEvidence -> deterministic evidence gate")
    add_narrative(d, [
        "STT is a separate local service and remains completely offline after an explicitly approved model download. Push-to-talk is delivered first. A local wake word is introduced only after the base speech loop meets accuracy, false-trigger and resource gates. The service owns microphone access, VAD, utterance boundaries, decoding and transcript normalization; it has no tool authority and never stores raw audio by default.",
        "Natural spoken Tanglish is the primary interaction target. Generic Whisper Base/Small, the Tamil-only fine-tune, Large-v3-turbo and full Large-v3 are measured regression baselines rather than certified command engines. Full Large-v3 achieved only one of five strict semantic successes, zero of four required slots, p95 real-time factor 12.77 and about 2.15 GiB peak RSS. Scaling generic Whisper is therefore closed unless materially new evidence appears.",
        "Each transcript event contains session and utterance identifiers, raw and alternative hypotheses when available, partial/final state, monotonic timestamps, segment confidence/no-speech signals, detected language spans, truncation status and the active privacy mode. STT never emits an authoritative command. Evidence-linked entity candidates retain their exact source span or hypothesis so downstream language reasoning cannot silently manufacture a critical target.",
        "Low-quality audio, absent critical entities or conflicting hypotheses produce repeat/clarification behavior. Personal evaluation audio and transcripts stay under the project storage root and are excluded from source control. The semantic decoder can improve transliteration and code-switch interpretation, but it cannot convert absent acoustic evidence into execution authority."
    ])
    d.table(["STT concern", "Design decision / certification gate"], [
        ["Model storage", "D:/Projects/Jarvis/storage/models/stt; hashes and licenses recorded beside model metadata"],
        ["Evaluation corpus", "Owner speech: natural Tanglish primary; pure Tamil/English controls; noise/distance conditions"],
        ["Performance", "Measure p50/p95 end-of-speech latency, real-time factor, peak RSS and CPU saturation"],
        ["Quality", "Semantic intent, slot/negation/entity preservation first; WER/CER remain diagnostic"],
        ["Concurrency", "Speech retains scheduler priority; OCR, local LLM and background tasks yield"],
        ["Privacy", "No cloud STT, no default raw-audio retention, explicit opt-in for diagnostic samples"],
        ["Failure", "Timeout/cancel worker, preserve the audio device, offer retry or typed-input fallback"],
    ], [2000, 6900])

    d.heading("3.7 Unified Tanglish companion and planner architecture", 2)
    d.code("TranscriptEvidence + typed trusted context + privacy labels\n"
           "        -> provider-neutral LLM gateway and deadline/budget\n"
           "        -> primary multilingual LLM (Tanglish + English + Tamil)\n"
           "        -> InteractionEnvelope: CHAT | ANSWER | CLARIFY | PLAN | MIXED\n"
           "        -> deterministic schema/dependency/reference validation\n"
           "        -> conversation response OR policy-bound PlanProposal\n"
           "        -> tools only after policy, approval and capability grant")
    add_narrative(d, [
        "Tanglish is open-domain owner language, not a finite command grammar. The primary multilingual LLM therefore handles casual companionship, questions, corrections, contextual references, clarifications and plan proposals in one conversational turn model. It may interpret imperfect STT using context, but it must not invent missing consequential targets. Missing recipient, file, application, scope or destructive intent produces a concise contextual clarification.",
        "The model returns one versioned InteractionEnvelope and has authority='none'. CHAT and ANSWER carry prose but no plan. CLARIFY carries one typed missing-field request and no plan. PLAN and MIXED carry a dependency-checked PlanProposal. Trusted code rejects contradictory modes, unknown dependencies, cycles, stale references and request-ID mismatches before policy sees the proposal.",
        "The gateway routes by purpose, privacy class, data labels, deadline and owner configuration. Azure OpenAI, OpenAI, Anthropic and local OpenAI-compatible/Ollama/llama.cpp profiles share the same internal request/response contract. Credentials are references into Windows user-bound DPAPI storage and are never placed in TOML, logs or prompts. SECRET or PROHIBITED data cannot use a remote route.",
        "The certified deterministic Tanglish decoder remains only an optional low-latency helper for reviewed phrases, cancellation markers and regression tests. It is not the boundary of what the owner may say and cannot override the LLM, policy or live context. Qwen3-8B Q4 remains rejected evidence and is not a runtime dependency."
    ])
    d.table(["Gateway gate", "Required behavior"], [
        ["Conversation", "Natural Tanglish companion responses remain relevant, concise and interruptible"],
        ["Clarification", "Missing consequential information produces one precise question and no executable plan"],
        ["Planning", "100% schema-valid, acyclic steps with explicit evidence and assumptions"],
        ["Authority", "Every model response declares authority=none; no provider invokes tools directly"],
        ["Privacy", "Local-only and secret/prohibited turns never leave the machine"],
        ["Providers", "The same conformance suite passes through every enabled adapter"],
        ["Performance", "Measure startup, p50/p95 latency, tokens, failures and system headroom per profile"],
        ["Fallback", "Unavailable or invalid providers fail closed or move only to a privacy-compatible profile"],
    ], [1900, 7000])
    d.code('{"request_id":"...","mode":"clarify","clarification":{"field":"target","question":"Endha app-ah close pannanum?"},"authority":"none"}')
    d.paragraph("The envelope is a proposal contract, not permission. Only the deterministic control plane can translate an accepted plan into canonical ActionIntents and scoped capabilities.")

    d.heading("3.8 Separate text-to-speech architecture", 2)
    d.code("STREAMED RESPONSE TEXT\n"
           "        -> safety/text normalizer + sentence chunker\n"
           "        -> language-span detector\n"
           "        -> editable English-to-Tamil pronunciation dictionary\n"
           "        -> local TTS engine/voice profile\n"
           "        -> bounded PCM queue + audio output\n"
           "        -> energy/phoneme cues -> Godot lip-sync\n"
           "        -> barge-in cancellation -> turn manager")
    add_narrative(d, [
        "TTS is an independently supervised local service. Its primary evaluation compares Tamil MMS VITS with AI4Bharat Indic-TTS on the target CPU. The initial mixed-language strategy uses one consistent Tamil-capable Jarvis voice and an editable pronunciation/transliteration dictionary so English technical terms remain understandable without switching personality. eSpeak NG Tamil is the emergency low-resource fallback.",
        "The service begins synthesis from bounded sentence or clause chunks rather than waiting for a complete answer. Playback uses a bounded queue and emits semantic speech state plus timing or energy cues for lip sync. Barge-in stops queued and active audio promptly while leaving any consequential tool transaction under the separate execution supervisor. Frequently used, non-sensitive phrases may be cached locally by normalized text, voice version and synthesis settings.",
        "Voice cloning and imitation are not part of the baseline. Any future cloned voice is an explicit opt-in asset with provenance and must never be used to impersonate the owner in communications. TTS telemetry records timing, engine/model version and resource use, not private response text."
    ])
    d.table(["TTS concern", "Design decision / certification gate"], [
        ["Model storage", "D:/Projects/Jarvis/storage/models/tts; voice license and provenance required"],
        ["Evaluation", "Tamil, English and mixed technical phrases rated for clarity, consistency and pronunciation"],
        ["Performance", "Measure time-to-first-audio, synthesis real-time factor, peak RSS and underruns"],
        ["Responsiveness", "Chunked streaming, bounded playback queue and immediate barge-in cancellation"],
        ["Fallback", "Certified primary voice -> lower-resource local voice -> eSpeak NG -> text-only response"],
        ["Character", "TTS emits timing/cues only; Godot owns visemes, animation blending and expression"],
        ["Privacy", "Offline synthesis, local phrase cache and no response text in operational telemetry"],
    ], [2000, 6900])

    d.heading("3.9 Final integrated Jarvis architecture", 2)
    d.code("EXPERIENCE:  Godot character | voice/text UI | trusted approval/settings UI\n"
           "                    |\n"
           "SPEECH:      VAD -> local STT -> TranscriptEvidence (untrusted)\n"
           "                    |\n"
           "COGNITION:   provider-neutral primary multilingual LLM gateway\n"
           "             -> CHAT | ANSWER | CLARIFY | PLAN | MIXED envelope\n"
           "                    | validated conversation / proposed plan\n"
           "ROUTING:     respond | clarify | validate and schedule proposed DAG\n"
           "                    | proposed typed ActionIntent / plan\n"
           "CONTROL:     privacy firewall -> schema/risk -> policy/approval gateway\n"
           "                    | signed, scoped capability\n"
           "CAPABILITY:  isolated agents/MCP tools + signed native Windows broker\n"
           "                    |\n"
           "EVIDENCE:    independent verifier -> response policy -> local TTS\n"
           "                    |\n"
           "STATE:       dialogue state | checkpoints | controlled memory | local storage\n"
           "\n"
           "Cross-cutting: inference scheduler | failure control plane | audit | emergency stop")
    add_narrative(d, [
        "This is architecture baseline v1.7. The user experiences one Jarvis personality, but acoustic sensing, primary reasoning, authorization, execution and verification remain separate trust domains. STT supplies evidence rather than commands. The primary multilingual LLM converses, clarifies and proposes plans through a provider-neutral gateway. The deterministic policy gateway and trusted approval UI issue narrow, expiring capability grants. Agents, MCP services and the Windows broker execute only those grants, and the verifier establishes outcomes from independent evidence.",
        "Language understanding is open-domain. The owner may speak arbitrary natural Tanglish, English or Tamil, including friendly conversation and mixed conversational/action turns. Deterministic parsing remains a useful fast path and safety signal, but it is not a vocabulary ceiling. The primary LLM receives the transcript as untrusted evidence, recent bounded dialogue state, trusted references, approved memories, privacy labels and only the capabilities relevant to planning.",
        "The primary LLM never receives raw speech as authority. It returns a typed interaction envelope. Missing consequential information creates a pending clarification; the answer resumes that exact turn without restarting the conversation. Accepted plans still undergo canonicalization, dependency checks, risk classification, policy and exact approval regardless of model confidence. A conversational response never creates an action implicitly.",
        "Phase 1 uses three distinct evidence sets. Owner speech recordings test acoustic recognition. Text variation resources test Tanglish normalization and semantic understanding. Original pattern-derived multi-turn dialogues test context, clarification, correction, concise status and proactive warnings. Tamil-dubbed superhero-assistant scenes inform behavior only; copyrighted audio or dialogue is not training data, and the test lines are original rather than transcripts.",
        "All large local assets use D:/Projects/Jarvis/storage. Models are separated by function; speech datasets, benchmark results, caches and temporary files have dedicated subdirectories. The project virtual environment is D:/Projects/Jarvis/.venv. Runtime configuration must redirect Hugging Face, PyTorch, pip and temporary caches into the project storage root so model downloads do not silently spread across the user profile.",
        "Development proceeds capability-first and evidence-first: foundation contracts and security controls, then the orchestration skeleton, safe Windows reads and app launch, certified speech, the character, controlled memory and increasingly capable supervised workflows. No later feature is allowed to bypass privacy, policy, verification, audit or resource-admission boundaries."
    ])

    # 4 flows
    d.heading("4. End-to-end runtime flows", 1)
    d.heading("4.1 Conversation-only request", 2)
    d.numbered("1", "Interaction service produces TranscriptEvidence with raw hypothesis, signal/segment quality and evidence-linked candidates.")
    d.numbered("2", "The evidence gate marks quality and unusable speech; deterministic markers may add hints but do not limit vocabulary.")
    d.numbered("3", "The privacy firewall creates the minimum permitted transcript, dialogue context, references and memory view.")
    d.numbered("4", "The primary multilingual LLM returns one InteractionEnvelope for chat, answer, clarification, planning or a mixed response.")
    d.numbered("5", "Trusted code validates the mode, request identity, references and plan graph; invalid output fails closed.")
    d.numbered("6", "The response streams to TTS and the character receives semantic animation cues, never bone-level commands.")
    d.numbered("7", "A memory candidate may be proposed, but storage requires the memory admission algorithm.")

    d.heading("4.2 Consequential desktop action", 2)
    d.code("STT evidence → privacy release → primary LLM InteractionEnvelope\n"
           "→ clarify missing information OR validate PlanProposal → create ActionIntent\n"
           "→ validate schema/canonical resources → evaluate OPA policy\n"
           "→ Preview and obtain trusted approval if required → Issue capability grant\n"
           "→ Prepare tool/broker → Recheck live target → Execute atomic action\n"
           "→ Verify independent postcondition → Commit, compensate or stop uncertain\n"
           "→ Audit and report → Consider safe memory")
    add_narrative(d, [
        "The action is not successful because a mouse click occurred or a tool returned a success string. Success requires evidence matching the declared postcondition. If evidence is contradictory or unavailable, the outcome becomes UNCERTAIN. Jarvis stops rather than blindly repeating an external action such as sending a message, purchasing or uploading.",
        "A desktop lease ensures that only one actuator controls the interactive session. Human keyboard or mouse activity revokes the lease immediately. The next automated action requires fresh context and, where necessary, a new grant."
    ])
    d.heading("4.3 Browser research flow", 2)
    add_narrative(d, [
        "A research request retrieves Brave Search, Context7, Playwright and MarkItDown from the catalog, then policy removes any tool incompatible with the data labels. Search queries are redacted. Results and pages are marked untrusted and retain URL/time provenance. Read-only retrieval can run in parallel within budgets. Documents are parsed in a sandbox, summarized as claims linked to sources and never treated as authority to perform a new action.",
        "Authenticated browser profiles are not used by default. A workflow needing a real account is a separate permission scope with explicit domain, profile and action restrictions. Downloads enter quarantine until type, size, hash and malware policy checks complete."
    ])
    d.heading("4.4 Failure and recovery", 2)
    d.table(["Failure class", "Response"], [
        ["Transient read failure", "Bounded retry with exponential backoff and jitter"],
        ["Idempotent mutation timeout", "Check idempotency record and postcondition before retry"],
        ["Non-idempotent uncertainty", "Stop, mark UNCERTAIN and request user review"],
        ["Changed UI target", "Discard stale target, reacquire UIA snapshot and re-authorize if scope changed"],
        ["Policy revocation", "Cancel pending execution, revoke lease and terminate restricted worker"],
        ["Tool health degradation", "Open circuit breaker and select an approved equivalent if policy allows"],
        ["Crash/restart", "Resume LangGraph checkpoint; never repeat committed effect"],
    ], [2500, 6400])

    # 5 Algorithms
    d.heading("5. Deep logic and algorithms", 1)
    d.heading("5.1 Controlled semantic decoding and structured intent construction", 2)
    add_narrative(d, [
        "The pipeline uses two different contracts. The semantic decoder produces an IntentEnvelope describing what the user appears to mean; it carries no authority. A deterministic router or primary planner then proposes an ActionIntent describing a possible effect. The ActionIntent contains the task, operation, canonical resources, purpose, data labels, destination, reversibility, expected effect and verification contract. Neither contract is itself permission.",
        "The decoder rubric is enforced as a protocol: semantic-compiler role only; transcript treated as untrusted data; no answers, plans, tools or chain-of-thought; one intent per turn; critical markers preserved; slots selected only from supplied evidence-linked candidates; trusted context used only for explicit references; ambiguity produces clarification. Grammar-constrained compact output reduces generated tokens and prevents prose from entering the action path.",
        "Intent construction is bounded. If the decoder or planner cannot identify the target, destination or scope, it asks for clarification or performs a separately permitted read-only discovery step. It must not use broad wildcards or world knowledge to compensate for uncertainty. Canonicalization occurs outside every model so aliases, relative paths, URL redirects and filesystem junctions cannot silently change the resource."
    ])
    d.code("function understand_turn(evidence, trusted_state):\n"
           "    if evidence_gate.rejects(evidence): return clarify('unclear_speech')\n"
           "    fast = deterministic_parser.match(evidence, trusted_state)\n"
           "    packet = fast or semantic_decoder.compact_output(shortlist(evidence), trusted_state)\n"
           "    envelope = semantic_validator.expand_and_validate(packet, evidence, trusted_state)\n"
           "    return envelope if envelope.valid else clarify(envelope.reason)\n"
           "\n"
           "function build_intent(envelope, context):\n"
           "    proposal = deterministic_plan(envelope) if envelope.intent in SIMPLE else \\\n"
           "               primary_planner.structured_output(envelope, context, ActionIntentSchema)\n"
           "    proposal.resource = canonicalize(proposal.resource)\n"
           "    validate_required_effects(proposal)\n"
           "    proposal.labels = join_labels(context.labels, proposal.payload_labels)\n"
           "    proposal.destination = resolve_destination(proposal)\n"
           "    return proposal")

    d.heading("5.2 Minimum-context acquisition", 2)
    add_narrative(d, [
        "Context acquisition follows a perception ladder: metadata, structured UIA/DOM, scoped screenshot, OCR/vision and finally raw coordinates. Each increase in fidelity has a privacy and cost penalty. The context builder selects the lowest level expected to satisfy the task and includes a justification in telemetry.",
        "A context item is admitted only when its expected utility exceeds its privacy exposure. A practical heuristic is U = relevance × confidence − sensitivity penalty − transmission penalty − staleness penalty. PROHIBITED items have infinite penalty and are never released. SECRET items remain local."
    ])

    d.heading("5.3 Hybrid tool retrieval and ranking", 2)
    add_narrative(d, [
        "The catalog can grow to hundreds of tools, but the planner receives only a small candidate set. Retrieval combines semantic similarity between the goal and approved tool contract, symbolic capability matching, data-policy compatibility, observed reliability, latency and cost. Hard policy incompatibilities remove a tool before scoring.",
        "An initial ranking formula is Score = 0.35 semantic relevance + 0.25 capability match + 0.15 reliability + 0.10 verification quality + 0.05 reversibility − 0.05 normalized latency − 0.05 normalized cost. Weights are configuration, not model output. Telemetry can recommend weight changes, but changes require review and evaluation."
    ])
    d.code("candidates = catalog.semantic_search(goal, k=30)\n"
           "candidates = [t for t in candidates if policy.pre_filter(t, task_scope)]\n"
           "for t in candidates:\n"
           "    t.score = weighted_rank(t, goal, historical_metrics)\n"
           "return diversity_select(candidates, maximum=8)")

    d.heading("5.4 Plan composition", 2)
    add_narrative(d, [
        "The planner produces a directed acyclic graph of typed steps. Edges represent data or effect dependencies. Read-only nodes without shared mutable resources may execute in parallel. Mutations are serialized per resource, and every external effect has a prepare/verify boundary. The composer rejects cycles, hidden tools and steps without declared postconditions.",
        "Plans are receding-horizon rather than fully open-loop: Jarvis plans enough to make progress, executes one consequential step, observes the actual state and replans. This preserves the useful ReAct pattern while preventing an unlimited autonomous loop."
    ])

    d.heading("5.5 Risk classification", 2)
    d.table(["Risk", "Meaning", "Default"], [
        ["R0", "Observation of non-sensitive state or public information", "Automatic"],
        ["R1", "Reversible local action inside a pre-approved scope", "Automatic within grant"],
        ["R2", "Local mutation or sensitive read", "Preview or session approval"],
        ["R3", "External communication, upload, install, purchase, elevation or irreversible action", "Exact one-shot approval"],
        ["R4", "Credential extraction, security bypass, hidden surveillance or prohibited impersonation", "Deny"],
    ], [900, 5200, 2800])
    add_narrative(d, [
        "Risk is computed using the maximum applicable rule, not an average. External destination, irreversible effect, elevated privilege, sensitive data, financial impact or uncertain identity can only raise risk. Deny rules override allows. An LLM estimate may inform explanation but cannot lower the deterministic classification."
    ])

    d.heading("5.6 Policy decision and capability issuance", 2)
    d.code("decision = opa.evaluate({identity, intent, tool_digest, resource, labels,\n"
           "                         destination, reversibility, environment, prior_approval})\n"
           "if decision == DENY: stop_and_audit()\n"
           "if decision == ASK_USER: approval = trusted_ui.exact_preview(intent)\n"
           "if approval missing/expired: stop_and_audit()\n"
           "grant = sign({task_id, tool_digest, operation, resource_scope, destination,\n"
           "              max_calls, expiry, approval_nonce, verification_obligations})")
    add_narrative(d, [
        "The grant is bearer authority constrained so narrowly that possession is insufficient for another operation. The runtime validates signature, audience, tool digest, task, expiry, call count and canonical resources. A changed destination, recipient, attachment, file set or executable identity requires reauthorization."
    ])

    d.heading("5.7 Transactional execution algorithm", 2)
    add_narrative(d, [
        "Every effectful operation implements PREPARE → AUTHORIZE → EXECUTE → VERIFY → COMMIT. PREPARE checks preconditions and produces a preview without irreversible effect. AUTHORIZE binds the preview to a policy decision and approval. EXECUTE performs one atomic effect. VERIFY uses evidence independent from the tool's narrative response. COMMIT records the result and releases temporary resources. Where supported, a compensation action is recorded before execution.",
        "Idempotency keys are derived from task, logical step and intended effect—not from retry count. Before executing, the runtime checks whether the same key already has a verified committed result. This prevents checkpoint replay from sending, uploading or writing twice."
    ])

    d.heading("5.8 Independent verification", 2)
    d.table(["Operation", "Primary evidence", "Secondary evidence"], [
        ["Open application", "Process path, signature/publisher and PID", "Expected top-level UIA window"],
        ["Write file", "Canonical path, hash and expected diff", "Size/timestamp and parse check"],
        ["Browser navigation", "Final origin/URL and DOM state", "Network/navigation event"],
        ["UI interaction", "Fresh element identity and resulting UIA state", "Scoped screenshot when needed"],
        ["Git change", "Repository status/diff/object identity", "Command exit and working tree checks"],
        ["External message", "Recipient/content digest and provider message ID", "Sent-folder/API confirmation"],
    ], [1800, 3800, 3200])
    add_narrative(d, [
        "Verification returns VERIFIED, FAILED or UNCERTAIN. VERIFIED requires all mandatory predicates. FAILED permits compensation if safe. UNCERTAIN never triggers a blind retry for non-idempotent actions. Vision can support evidence but must not be the only verifier for high-risk operations when process, filesystem, API or UIA evidence exists."
    ])

    d.heading("5.9 UI grounding algorithm", 2)
    d.code("1. Enumerate top-level windows and verify process path/publisher.\n"
           "2. Acquire a fresh UI Automation tree for the permitted window.\n"
           "3. Retrieve candidates by role, accessible name, automation ID and ancestry.\n"
           "4. Score candidates; reject ambiguity above the configured margin.\n"
           "5. Recheck focus, enabled state and bounding rectangle immediately before action.\n"
           "6. Invoke the semantic UIA pattern; use pointer coordinates only as a last fallback.\n"
           "7. Observe the declared postcondition and record evidence.")
    add_narrative(d, [
        "Stable semantic identifiers are preferred over pixels. If the interface changes and candidate confidence falls below threshold, Jarvis asks or stops. Coordinate clicks expire after the originating snapshot and cannot be reused after window movement, scaling or focus changes."
    ])

    d.heading("5.10 Privacy classification and release", 2)
    d.table(["Label", "Handling"], [
        ["PUBLIC", "May use approved endpoints subject to task policy"],
        ["PERSONAL", "Minimum necessary context; redact unnecessary identifiers"],
        ["CONFIDENTIAL", "Local processing preferred; explicit endpoint release policy"],
        ["SECRET", "Never leaves the device; short retention and restricted access"],
        ["PROHIBITED", "No model/tool release or memory: credentials, cookies, private keys, passwords"],
    ], [1700, 7200])
    add_narrative(d, [
        "Classification combines deterministic patterns, source policy and local PII detection. Source policy dominates: a password field remains PROHIBITED even if a detector misses it. Redaction creates a release view while retaining only a local short-lived mapping when the task genuinely needs reconstruction. Logs receive a separately defined telemetry view, not the prompt payload."
    ])

    d.heading("5.11 Memory admission and retrieval", 2)
    d.code("candidate → classify sensitivity → verify source/provenance\n"
           "→ reject credentials/private-mode content → detect contradiction/duplication\n"
           "→ choose memory class and retention → require consent when policy says so\n"
           "→ store content + source + confidence + labels + expiry")
    add_narrative(d, [
        "Retrieval is hybrid: semantic similarity, keyword/entity match, recency, confidence and permission scope. A suggested ranking is 0.35 semantic + 0.20 entity + 0.15 recency + 0.15 confidence + 0.15 task relevance, followed by a hard permission filter. Web and document claims enter quarantine and cannot become procedural instructions until validated.",
        "Procedural memory is versioned code/data representing an approved workflow. Learning from demonstration produces a draft skill with observed preconditions and steps. It is replayed in shadow mode, tested, reviewed and signed before trusted routine status."
    ])

    d.heading("5.12 Proactivity algorithm", 2)
    add_narrative(d, [
        "Proactivity begins with deterministic triggers rather than continuous model speculation. Each rule defines allowed observations, quiet hours, cooldown, frequency budget, confidence threshold, permitted response and expiry. A relevance score combines urgency, expected value, confidence, interruption cost and recent notification load. The action is suppressed unless relevance exceeds threshold and all budgets permit it.",
        "Every interruption includes a human-readable reason. Proactive permission never implies permission to perform a consequential tool action; the resulting action still follows the normal policy pipeline."
    ])

    d.heading("5.13 Voice and turn-taking logic", 2)
    add_narrative(d, [
        "The voice loop separates wake-word/VAD from reasoning. Local VAD and echo cancellation determine speech segments; streaming STT emits partial text; the intent router can acknowledge locally while a remote model works. Barge-in cancels TTS playback and returns the graph to listening without discarding a running tool transaction. Speaker recognition personalizes but never authorizes R3 actions.",
        "Voice imitation, gesture imitation and workflow imitation are separate opt-in features. A cloned voice must not be used to contact another person without exact approval."
    ])

    d.heading("5.14 Character behavior state machine", 2)
    d.code("SLEEPING ↔ IDLE ↔ LISTENING → THINKING → SPEAKING\n"
           "                       │            │\n"
           "                       ▼            ▼\n"
           "                    EXECUTING ↔ WAITING_APPROVAL\n"
           "                       │\n"
           "                  BLOCKED / ERROR")
    add_narrative(d, [
        "LangGraph emits semantic cues such as emotion, intensity, activity, gesture target and speech state. Godot owns animation blending, navigation, collision avoidance and secondary motion. The model never controls bones or screen coordinates. Privacy state overrides expressive state: in Private mode the character visibly covers its eyes or adopts a distinct disabled state."
    ])

    d.heading("5.15 Execution resilience and the Failure Control Plane", 2)
    add_narrative(d, [
        "Failure handling is a runtime responsibility, not a language-model responsibility. The LLM may interpret an error, suggest corrected arguments or propose a revised plan, but deterministic services decide whether a call may be retried, skipped, replaced, compensated, cancelled or escalated to the user. This remains true even when a multi-agent worker, MCP server or third-party tool contains its own internal loop.",
        "Jarvis therefore includes a Failure Control Plane spanning LangGraph, the Tool Capability Platform, the policy gateway, runtime supervisors, the independent verifier, the transaction journal and the progress system. Every call is supervised from outside the potentially unreliable component. A component cannot extend its deadline, reset its attempt counter, declare its own effect verified or hide its failure from the parent task."
    ])
    d.code("LANGGRAPH SUPERVISOR\n"
           "        │\n"
           "        ▼\n"
           "EXECUTION ENVELOPE + BUDGET MANAGER\n"
           "        │\n"
           "        ▼\n"
           "AGENT / LLM / MCP / NATIVE TOOL\n"
           "        │\n"
           "        ▼\n"
           "INDEPENDENT VERIFIER → FAILURE CLASSIFIER\n"
           "        │\n"
           "        ├→ bounded retry\n"
           "        ├→ approved fallback\n"
           "        ├→ bounded replan\n"
           "        ├→ compensate / roll back\n"
           "        └→ fail, uncertain, cancel or ask user")

    d.heading("5.16 Execution envelope", 2)
    add_narrative(d, [
        "Every LLM request, graph worker, MCP invocation and native broker action receives an immutable execution envelope. The envelope is created by the runtime from the task profile, tool contract and policy decision. A child receives a subset of the remaining parent budget; it never receives a fresh independent budget.",
        "The envelope contains an absolute deadline, per-attempt timeout, maximum attempts, maximum logical steps, recursion depth, maximum child workers, token and financial limits, maximum output size, cancellation token, idempotency key, declared postcondition, approved fallback set, compensation action and criticality. The model can request more time through a structured proposal, but only policy or the user can approve an extension."
    ])
    d.table(["Envelope field", "Purpose"], [
        ["task_id / trace_id", "Correlate graph state, tools, evidence, audit and progress"],
        ["absolute_deadline", "Hard wall-clock boundary shared by descendants"],
        ["attempt / max_attempts", "Prevent unbounded retry loops"],
        ["step_count / max_steps", "Bound reasoning, tool and replan transitions"],
        ["depth / max_depth", "Bound multi-agent recursion"],
        ["max_workers", "Bound fan-out and concurrent work"],
        ["token/cost/call budgets", "Bound model and external resource consumption"],
        ["cancellation_token", "Propagate pause, stop, revocation and user takeover"],
        ["idempotency_key", "Identify one logical effect across retries and restarts"],
        ["postcondition", "Define evidence required before success"],
        ["fallback_set", "Restrict alternatives to pre-approved compatible tools"],
        ["compensation", "Define safe reversal where supported"],
        ["criticality", "Required, optional, best-effort, compensatable or irreversible"],
    ], [2500, 6400])

    d.heading("5.17 Default attempt and timeout policy", 2)
    add_narrative(d, [
        "The following defaults are conservative production starting points. max_attempts includes the initial attempt. Individual tool contracts may be stricter. A policy hard cap always overrides a contract or task profile, and an LLM can never increase the values. Rate-limit responses may use Retry-After only when the remaining task deadline permits it."
    ])
    d.table(["Operation", "Max attempts", "Per-attempt timeout", "Retry condition"], [
        ["Tanglish semantic decode", "1", "5-second initial hard cap", "No repair retry; timeout/invalid output clarifies"],
        ["Primary LLM reasoning", "3", "45 seconds", "Transport or invalid structured output within budget"],
        ["Complex LLM reasoning", "2", "90 seconds", "Approved Deep profile only"],
        ["Structured-output repair", "2", "20 seconds", "One bounded repair cycle"],
        ["Local read-only operation", "3", "10 seconds", "Transient failure"],
        ["Network search/read", "3", "20 seconds", "Transient/read-only with backoff"],
        ["Browser navigation", "2", "30 seconds", "Fresh navigation context"],
        ["Application launch", "2", "30 seconds", "Verifier proves app did not start"],
        ["Windows UIA operation", "2", "10 seconds", "Fresh UIA snapshot proves no effect"],
        ["File write/rename", "2", "30 seconds", "Only idempotent or reconciled mutation"],
        ["Document conversion", "2", "60–180 seconds", "Based on type/size contract"],
        ["MCP process startup", "2", "20 seconds", "Clean prior process termination"],
        ["MCP health check", "2", "5 seconds", "No side effect"],
        ["Normal MCP call", "3", "30 seconds", "Read-only/idempotent contract"],
        ["Long approved MCP call", "2", "120 seconds", "Explicit long-running contract"],
        ["External message/upload", "1", "60 seconds", "Never retry before reconciliation"],
        ["Purchase/elevation/install", "1", "Operation-specific", "No automatic retry"],
        ["Policy denial or rejected approval", "1", "Immediate", "Terminal unless user creates a new task/approval"],
        ["Uncertain external effect", "1", "Reconciliation only", "Never repeat the effect blindly"],
    ], [2700, 1200, 1800, 3200])
    add_narrative(d, [
        "Timeouts should later be tuned from observed, privacy-safe performance: effective_timeout = min(policy_hard_cap, max(contract_minimum, historical_p95 × 1.5 + startup_margin)). File size, document type or declared workload may select among approved timeout classes, but runtime history never weakens a security boundary. Cancellation has a short cooperative grace period, followed by termination of the restricted worker when it does not comply."
    ])

    d.heading("5.18 Logical-step, recursion and task-duration budgets", 2)
    d.table(["Scope", "Initial default", "Hard production guidance"], [
        ["Conversation-only graph", "4 logical steps", "No tool-actuation loop"],
        ["Standard tool task", "12 logical steps", "20 tool calls maximum"],
        ["Research/coding workflow", "25 logical steps", "40 tool calls maximum"],
        ["Supervised complex workflow", "40 total steps", "Must expose step plan/progress"],
        ["Individual specialist agent", "8 steps", "Returns INCOMPLETE when exhausted"],
        ["Replans", "2", "New plan must remain within original scope"],
        ["Fallback switches", "1", "Approved equivalent only"],
        ["Verification attempts", "2", "Then FAILED or UNCERTAIN"],
        ["Concurrent workers", "3", "All share parent budget"],
        ["Workers created per task", "5", "No self-reset by respawning"],
        ["Agent recursion", "Depth 1", "Absolute maximum depth 2 after maturity"],
    ], [2700, 2500, 3700])
    d.table(["Task profile", "Wall-clock budget", "Behavior"], [
        ["Instant", "30 seconds", "Small conversation/classification; no extended background work"],
        ["Standard", "5 minutes", "Default interactive task"],
        ["Deep", "20 minutes", "Explicit research/coding profile with periodic progress"],
        ["Background", "60 minutes", "Explicit background mode, cancellation and scheduled updates"],
        ["Beyond profile", "User continuation required", "Checkpoint safely before requesting extension"],
    ], [1800, 2200, 5000])
    add_narrative(d, [
        "Depth is measured from the root supervisor at depth 0. The MVP permits root → specialist only; specialists cannot spawn helpers. A mature deployment may permit one narrow helper at depth 2 for reviewed workflows. MCP servers cannot autonomously call other MCP servers. Tool composition remains visible to the root supervisor so budgets, policy and provenance cannot be bypassed through hidden call chains."
    ])

    d.heading("5.19 Execution and failure state machine", 2)
    d.code("PENDING → PREPARED → AUTHORIZED → RUNNING\n"
           "                                │\n"
           "                                ▼\n"
           "                    SUCCEEDED_UNVERIFIED\n"
           "                                │\n"
           "                                ▼\n"
           "                         VERIFIED → COMMITTED\n"
           "\n"
           "RUNNING / VERIFYING failure branches:\n"
           "RETRY_WAIT | FALLBACK | REPLAN_REQUIRED | COMPENSATING\n"
           "FAILED | UNCERTAIN | CANCELLED | BLOCKED")
    add_narrative(d, [
        "A tool response marked success moves only to SUCCEEDED_UNVERIFIED. COMMITTED requires independent verification. State transitions are written to the transaction journal before the next effect. Terminal states always produce a user-facing result and an audit event; there is no silent suppression of a failed required step."
    ])

    d.heading("5.20 Failure taxonomy and deterministic response", 2)
    d.table(["Failure class", "Runtime response"], [
        ["Schema/argument error", "One bounded correction or replan; never broaden target to hide ambiguity"],
        ["Policy denial", "Stop. The LLM cannot retry, rephrase around or bypass policy"],
        ["Approval rejected/expired", "Cancel intent and revoke pending grant"],
        ["Transient network/rate failure", "Bounded exponential backoff with jitter within deadline"],
        ["Permanent tool error", "Approved fallback or bounded replan; otherwise fail"],
        ["Tool unavailable/unhealthy", "Open circuit breaker; do not repeatedly start a failing server"],
        ["Timeout before proven effect", "Retry only if tool contract and evidence say safe"],
        ["Timeout after possible effect", "Reconcile actual state; otherwise UNCERTAIN"],
        ["Verification failure", "Compensate when safe, otherwise fail with evidence"],
        ["Budget exhausted", "Checkpoint, stop or ask the user for an explicit extension"],
        ["Prompt injection/tainted control", "Quarantine input, deny derived action and record security event"],
        ["User takeover/cancel", "Revoke desktop lease, propagate cancellation and preserve consistent state"],
        ["Hung process/container", "Cooperative cancel, then forced termination and health penalty"],
        ["Partial workflow failure", "Preserve verified work; compensate affected mutations; evaluate dependencies"],
        ["Runtime crash/restart", "Load checkpoint and reconcile journal before executing anything"],
    ], [3000, 6000])

    d.heading("5.21 Criticality and controlled continuation", 2)
    d.table(["Step class", "May Jarvis continue?", "Required behavior"], [
        ["Required", "No, not through dependent steps", "Replan within scope, ask user or fail"],
        ["Optional", "Yes", "Mark skipped and disclose in final report"],
        ["Best effort", "Yes with approved fallback", "Preserve warning and reduced-quality evidence"],
        ["Compensatable", "Only after compensation succeeds or user accepts state", "Verify rollback"],
        ["Irreversible", "No on uncertainty", "Exact approval, one attempt and user review"],
    ], [1800, 2500, 4700])
    add_narrative(d, [
        "The plan DAG determines which downstream nodes depend on a failed result. Independent branches may continue when policy permits. Jarvis must never use an optional classification to conceal a required data source, security check or verification predicate. The final report lists skipped, degraded, fallback and uncertain steps separately from verified completion."
    ])

    d.heading("5.22 Retry safety, reconciliation and idempotency", 2)
    add_narrative(d, [
        "The Tool Harness owns retry safety because it has the tool contract, effect declaration and idempotency semantics. Safe automatic retries include public search, read-only file access and APIs with verified idempotency keys. Unsafe automatic retries include messages, purchases, uploads, installations, changing UI operations and mutations whose first outcome is unknown.",
        "Before any retry the harness checks the idempotency registry and invokes a reconciliation adapter. Reconciliation queries the real provider, filesystem, repository, process or UI state using the same logical effect identifier. If the effect is already present, Jarvis verifies and commits it instead of repeating it. If absence is proven, a permitted retry can proceed. If neither is provable, the result is UNCERTAIN and the user decides."
    ])
    d.code("on_failure(call, error):\n"
           "    class = classify(error, call.contract, observed_evidence)\n"
           "    if class is POLICY_OR_APPROVAL: return STOP\n"
           "    if effect_may_have_occurred:\n"
           "        state = reconcile(call.idempotency_key, call.postcondition)\n"
           "        if state == PRESENT: return VERIFY_AND_COMMIT\n"
           "        if state == UNKNOWN: return UNCERTAIN\n"
           "    if retryable(class) and budget.remaining_attempts > 0:\n"
           "        return RETRY_WITH_BACKOFF\n"
           "    return approved_fallback_or_replan_or_fail()")

    d.heading("5.23 Multi-agent containment", 2)
    add_narrative(d, [
        "A multi-agent worker is a bounded graph worker, not an independent authority. It receives a narrow goal, selected tools, remaining shared budget, deadline, expected structured result and cancellation token. Workers return evidence, proposals or INCOMPLETE; they cannot approve actions, modify policies, install tools, change budgets or declare external effects committed.",
        "The root supervisor owns the task DAG and all side-effect sequencing. Fan-out is used mainly for independent read-only research or analysis. Mutating proposals from workers return to the root for intent construction, policy and ordered execution. A child failure cannot be hidden by a free-text summary because completion is derived from structured worker status and required evidence."
    ])
    d.code("Root supervisor (depth 0)\n"
           "├─ Research worker (depth 1, read-only, 8 steps)\n"
           "├─ Coding analysis worker (depth 1, no deployment authority)\n"
           "└─ Verification worker (depth 1, evidence only)\n"
           "\n"
           "MVP rule: depth-1 workers cannot spawn another worker.")

    d.heading("5.24 MCP and opaque internal-loop containment", 2)
    add_narrative(d, [
        "Jarvis may not observe every loop inside a third-party MCP server. The runtime therefore controls the process externally: absolute timeout, CPU/memory/process/output limits, restricted filesystem and network, health/heartbeat checks, cancellation, forced termination, call budget and circuit breaker. OpenTelemetry measures the outer call even when the server has no instrumentation.",
        "A server that exceeds limits, emits contract-breaking output, changes schema/digest or ignores cancellation is penalized and may be quarantined. The model cannot immediately select the same unhealthy server under a new name. Equivalent fallback requires a separately approved contract and compatible data-destination policy."
    ])

    d.heading("5.25 Compensation and crash recovery", 2)
    d.table(["Effect", "Prepared recovery"], [
        ["File edit", "Backup, original hash and atomic replace/restore"],
        ["Rename/move", "Recorded source/destination and reversible move"],
        ["Delete", "Recycle Bin or quarantine; permanent deletion is separately restricted"],
        ["Git mutation", "Original object/reference and working-tree diff"],
        ["UI setting", "Read and record previous value before change"],
        ["Draft message", "Delete draft if provider confirms draft identity"],
        ["Delivered message/purchase", "Generally irreversible; require stronger approval and reconciliation"],
    ], [2400, 6500])
    add_narrative(d, [
        "After a crash, Jarvis loads the last LangGraph checkpoint, reads prepared/running/committed journal records and reconciles each non-terminal operation against real state. Already verified effects are skipped. Safe pending reads may resume. Ambiguous external effects become UNCERTAIN. The user receives a recovery summary before the graph continues with new consequential work."
    ])

    d.heading("5.26 Live progress architecture for the character", 2)
    add_narrative(d, [
        "The character is the primary human-readable view of backend progress. It must never appear frozen during model, agent, MCP or verification work. Progress is generated by a deterministic Progress Aggregator consuming structured runtime events; the LLM does not invent percentages or claim that an operation is almost complete.",
        "The aggregator joins graph state, execution envelopes, tool spans, verification results and budgets into a safe display view. Raw secrets, prompts, private document bodies and tool payloads are never sent to the character process. Human-readable messages come from approved templates populated with safe metadata such as operation category, application name, attempt number and elapsed time."
    ])
    d.code("LANGGRAPH / BUDGET MANAGER / TOOL HARNESS / VERIFIER\n"
           "                         │ structured progress events\n"
           "                         ▼\n"
           "                 RUNTIME EVENT BUS\n"
           "                         ▼\n"
           "                 PROGRESS AGGREGATOR\n"
           "                         ▼\n"
           "              CHARACTER STATE CONTROLLER\n"
           "                         ▼\n"
           "       ANIMATION + STATUS CARD + OPTIONAL VOICE UPDATE")

    d.heading("5.27 Character status vocabulary", 2)
    d.table(["Runtime state", "Character indication", "User-facing information"], [
        ["LISTENING", "Attentive pose and listening animation", "Input capture mode and privacy indicator"],
        ["UNDERSTANDING", "Brief attentive/thinking transition", "Interpreting the request"],
        ["PLANNING", "Calm thinking animation", "Building a bounded plan"],
        ["WAITING_APPROVAL", "Amber state; points to trusted window", "Exact action awaits approval"],
        ["EXECUTING", "Working animation", "Current safe operation/tool category"],
        ["VERIFYING", "Inspection/check animation", "Checking whether the effect actually occurred"],
        ["RETRYING", "Orange caution state", "Attempt n of maximum and safe reason"],
        ["REPLANNING", "Route-change animation", "Original method failed; evaluating approved alternative"],
        ["DEGRADED", "Subtle warning", "Optional part skipped or fallback quality limitation"],
        ["BLOCKED", "Red/paused state", "Dependency, policy or environment prevents progress"],
        ["UNCERTAIN", "Stops and requests attention", "Effect may have happened; no retry performed"],
        ["COMPLETED", "Short success response", "Verified results and any limitations"],
        ["PRIVATE", "Covers eyes/turns away", "Observation is disabled for this context"],
        ["CANCELLED", "Neutral stop transition", "What stopped and what state was preserved"],
    ], [1800, 3100, 4100])

    d.heading("5.28 Honest progress calculation", 2)
    add_narrative(d, [
        "Jarvis uses determinate progress only when a stable execution DAG exists. Completion is based on weighted VERIFIED or safely skipped terminal steps, never merely dispatched calls. A step in SUCCEEDED_UNVERIFIED does not count as complete. Weights can use declared complexity or historical median duration, bounded so one uncertain model call cannot generate misleading precision.",
        "When plan length is unknown—such as waiting on an LLM or opaque external service—the UI uses indeterminate animation and shows elapsed time, current deadline and operation category. If replanning changes the DAG, the character states that the plan changed and reports remaining verified steps instead of making the percentage move backward without explanation."
    ])
    d.code("Determinate:\n"
           "  Researching project — 4 of 7 verified steps complete\n"
           "  Current: converting the selected document\n"
           "  Elapsed: 1m 24s\n"
           "\n"
           "Indeterminate:\n"
           "  Analyzing the document…\n"
           "  Waiting for the reasoning endpoint\n"
           "  Elapsed: 18s • Timeout: 45s")

    d.heading("5.29 Progress event contract", 2)
    d.code('{\n'
           '  "task_id": "task-123",\n'
           '  "trace_id": "trace-456",\n'
           '  "state": "EXECUTING",\n'
           '  "phase": "TOOL_CALL",\n'
           '  "step": 4, "total_steps": 7,\n'
           '  "progress_mode": "DETERMINATE",\n'
           '  "verified_progress": 57,\n'
           '  "message_code": "DOCUMENT_CONVERTING",\n'
           '  "safe_display_args": {"document_type": "PDF"},\n'
           '  "tool_id": "markitdown.convert",\n'
           '  "attempt": 1, "maximum_attempts": 2,\n'
           '  "elapsed_seconds": 18, "timeout_seconds": 60,\n'
           '  "user_action_required": false\n'
           '}')
    add_narrative(d, [
        "Progress events are versioned, ordered per task and idempotent. The character ignores stale sequence numbers. Event generation is rate-limited so high-frequency tool logs do not cause animation jitter or notification fatigue. Important transitions—approval, retry, fallback, uncertainty, block, cancellation and completion—are never coalesced away."
    ])

    d.heading("5.30 Execution controls and detail levels", 2)
    add_narrative(d, [
        "The progress card provides Pause, Cancel, Emergency Stop, Show Details and Open Timeline. A budget-extension action checkpoints safely and creates a new policy/user decision; it does not mutate the existing envelope silently. Normal mode uses simple language. Developer mode may show graph node, MCP/tool identity, attempt count, remaining timeout, policy decision, trace ID, verification evidence and token/cost usage.",
        "Pause is cooperative for reasoning/read operations but cannot freeze an external operation at an unsafe point. The runtime either reaches a safe checkpoint or completes/compensates the current atomic effect before reporting PAUSED. Emergency Stop immediately revokes leases/grants and terminates restricted workers, then performs recovery assessment."
    ])

    d.heading("5.31 Curated resilience services", 2)
    d.table(["Service", "Owned behavior"], [
        ["Budget Manager", "Attempts, steps, recursion, workers, tool calls, wall time, tokens and cost; parent/child budget accounting"],
        ["Failure Controller", "Error taxonomy, retry eligibility, backoff, fallback, replans, compensation, uncertainty and circuit breakers"],
        ["Progress Aggregator", "Task progress, safe status messages, character events, elapsed/deadline display and user controls"],
        ["Transaction Journal", "Prepared/running/verified/committed state, idempotency and crash reconciliation"],
        ["Independent Verifier", "Evidence predicates and VERIFIED/FAILED/UNCERTAIN outcome"],
    ], [2500, 6400])
    add_narrative(d, [
        "These services use a shared error taxonomy and event model. Every tool contract supplies retry class, timeout class, criticality, idempotency, postconditions and compensation. Every graph node declares consumed and produced state. Fault-injection tests then prove behavior for timeout, crash, cancellation, duplicate delivery, partial effect, stale UI and unavailable provider before a capability reaches production."
    ])

    d.heading("5.32 Failure ownership and authority", 2)
    d.table(["Responsibility", "Owner", "Boundary"], [
        ["Timeouts, budgets and recursion limits", "Jarvis runtime", "Creates immutable envelopes; LLM cannot extend them"],
        ["Retry safety and idempotency", "Tool Harness", "Uses signed tool contracts, journal and reconciliation"],
        ["Policy and permission decisions", "OPA / Policy Gateway", "Deny precedence; approval obligations and scoped grants"],
        ["Process termination and containment", "ToolHive / Windows Broker", "Container/process/OS enforcement independent of model"],
        ["Postcondition verification", "Independent Verifier", "Tool self-report is insufficient"],
        ["Recovery and compensation", "LangGraph Failure Controller", "Orchestrates rollback, replan, checkpoint and terminal outcome"],
        ["Diagnosis and revised plan", "LLM", "Advisory structured proposal; no authority or success declaration"],
        ["Uncertain/high-impact decision", "User", "Trusted UI decision after exact state/evidence presentation"],
        ["Failure history", "Audit journal and OpenTelemetry", "Authoritative security events plus operational traces/metrics"],
    ], [3100, 2500, 3300])
    d.paragraph("Governing rule: the LLM may recommend recovery, but the Jarvis Failure Control Plane controls recovery. Jarvis may continue past a genuinely optional failure only when dependency analysis, policy and the plan's declared criticality allow it; it must never silently bypass a required, unsafe or uncertain failure.", bold=True, color="8C3B3B")

    # 6 strategies
    d.heading("6. Effective engineering and product strategies", 1)
    strategies = [
        ("API and semantic automation first", "Prefer official APIs, DOM and UI Automation over screenshots and pixels. This improves reliability, reduces token cost and creates verifiable state."),
        ("Small excellent capability set", "Launch with roughly 10–15 capabilities that have contracts, tests and evidence. Expand by adding verified skills rather than broad authority."),
        ("Progressive disclosure", "Retrieve a small task-relevant tool set instead of exposing the full catalog to the model."),
        ("Autonomy ladder", "Shadow mode → assistant preparation → supervised execution → trusted reversible routines → constrained proactivity."),
        ("Receding-horizon planning", "Execute and verify one consequential step before replanning from actual state."),
        ("Provider-neutral routing", "Use model profiles for reasoning, fast classification and optional vision, each constrained by data labels and budgets."),
        ("Security before breadth", "Build ActionIntent, policy, approval, audit and verification before powerful desktop control."),
        ("Evidence-driven improvement", "Use telemetry and benchmark results to tune routing and reliability; never learn authority from success frequency."),
        ("Human takeover is normal", "Treat user interruption as a supported state transition rather than an error."),
        ("Targeted experimentation", "Use short spikes for uncertain technologies; avoid reopening settled architecture without evidence."),
    ]
    for title, body in strategies:
        p = d.paragraph()
        d.run(p, title + ": ", bold=True, color="16324F")
        d.run(p, body)

    # 7 Tool harness architecture
    d.heading("7. Jarvis Tool Capability Platform — separate architecture", 1)
    d.heading("7.1 Purpose", 2)
    add_narrative(d, [
        "The Tool Capability Platform is the complete harness around MCP and native tools. It is not merely a protocol client. It helps Jarvis discover the right capability, understand its contract, compose it with other capabilities, obtain authority, execute in isolation, normalize output, verify effects and learn operational reliability. MCP supplies a useful interoperability protocol; the platform supplies governance and effectiveness.",
        "Standalone MCP services are used for capabilities that touch files, applications, accounts, networks or devices. Small pure computations may remain internal graph nodes. This preserves the requirement that meaningful tools are versioned services rather than loose Python functions imported into the agent."
    ])
    d.code("LANGGRAPH GOAL\n"
           "   ▼\n"
           "CATALOG → HYBRID RETRIEVER → TOOL COMPOSER → PREFLIGHT/SIMULATION\n"
           "                                      ▼\n"
           "                         POLICY ENFORCEMENT POINT\n"
           "                                      ▼\n"
           "                     CAPABILITY + SECRET BROKER\n"
           "                         ┌──────────┴──────────┐\n"
           "                         ▼                     ▼\n"
           "                TOOLHIVE MCP RUNTIME     WINDOWS BROKER\n"
           "                         └──────────┬──────────┘\n"
           "                            NORMALIZER\n"
           "                                ▼\n"
           "                             VERIFIER\n"
           "                                ▼\n"
           "                   OUTCOME METRICS / AUDIT / GRAPH")
    d.heading("7.2 Platform components", 2)
    d.table(["Subsystem", "Logic"], [
        ["Trusted registry", "Approved identity, publisher, digest, schemas, permissions and lifecycle state"],
        ["Contract store", "Effects, risks, destinations, pre/postconditions, retries, rollback and verification"],
        ["Semantic index", "Embeddings plus symbolic capability/label indexes; no authority encoded in embeddings"],
        ["Retriever/ranker", "Selects a diverse, policy-compatible 5–10 tool candidate set"],
        ["Composer", "Builds a dependency DAG and serializes conflicting effects"],
        ["Preflight", "Validates arguments, previews diffs/effects, estimates cost and checks budgets"],
        ["PEP adapter", "Obtains an OPA decision and binds exact approval to a grant"],
        ["Secret broker", "Injects scoped credentials at runtime; secrets never enter prompts"],
        ["Runtime supervisor", "Starts pinned workloads, enforces mounts/egress/limits, cancellation and health"],
        ["Result normalizer", "Produces a common envelope with provenance, side effects, evidence and warnings"],
        ["Verifier", "Checks declared predicates independently and controls commit/compensation"],
        ["Evaluator", "Measures reliability, selection accuracy, latency and cost for reviewed ranking updates"],
    ], [2300, 6600])
    d.heading("7.3 Tool contract", 2)
    d.code("identity: browser.navigate\n"
           "publisher: microsoft\n"
           "server_digest: sha256:...\n"
           "input_schema: {url, expected_origin}\n"
           "effects: [network.read, browser.navigate]\n"
           "data_destinations: [requested_origin]\n"
           "risk: R1\n"
           "preconditions: [isolated_profile_ready]\n"
           "postconditions: [final_origin_matches, page_state_available]\n"
           "approval: policy_dependent\n"
           "timeout_seconds: 30\n"
           "retry: read_only_bounded\n"
           "verification: url_origin_and_dom_state")
    add_narrative(d, [
        "The trusted contract is owned by Jarvis and signed during onboarding. Runtime descriptions from tools/list are compared with the approved schema and hash but never treated as authority. An unexpected schema, description, binary or dependency change moves the server to quarantine."
    ])
    d.heading("7.4 Onboarding lifecycle", 2)
    d.code("Discover → quarantine download → verify publisher/license → pin release/digest\n"
           "→ generate SBOM → scan source/dependencies/configuration → inspect schemas/effects\n"
           "→ adversarial tests in disposable environment → assign capabilities\n"
           "→ human approval → sign contract → promote → continuously monitor")
    d.heading("7.5 Runtime lifecycle", 2)
    d.code("Goal → retrieve candidates → policy pre-filter → plan/compose → schema validation\n"
           "→ privacy and destination check → risk/approval → capability grant\n"
           "→ isolated execution → output limits/sanitization → independent verification\n"
           "→ commit/compensate/uncertain → audit and metrics")
    d.heading("7.6 Common result envelope", 2)
    d.code('{\n'
           '  "status": "VERIFIED | FAILED | UNCERTAIN",\n'
           '  "data": {},\n'
           '  "provenance": {"server_digest": "...", "sources": []},\n'
           '  "side_effects": [],\n'
           '  "verification_evidence": [],\n'
           '  "warnings": [],\n'
           '  "trace_id": "...",\n'
           '  "audit_event_ids": []\n'
           '}')
    d.heading("7.7 Isolation and reliability", 2)
    for x in [
        "ToolHive containers for network/document MCP services; native restricted broker for interactive Windows.",
        "No inherited shell environment; separate secrets; network deny-by-default and approved read-only mounts.",
        "CPU, memory, process, output-size, time, call-count, recursion and monetary budgets.",
        "Circuit breakers, health probes, graceful cancellation and quarantine after repeated contract violations.",
        "Parallelism only for independent read-only calls; per-resource locks for mutations.",
        "Idempotency and compensation metadata determine retry behavior; the model does not decide retry safety.",
        "SSRF controls block localhost, private ranges and metadata endpoints unless explicitly granted."
    ]:
        d.bullet(x)
    d.heading("7.8 Initial capability portfolio", 2)
    d.table(["Capability", "Implementation", "Initial mode"], [
        ["Browser", "Microsoft Playwright MCP", "Isolated profile, domain policy, quarantined downloads"],
        ["Filesystem", "Wrapped MCP reference server", "Approved roots; read-only; staged writes"],
        ["Git", "Wrapped MCP Git", "Read-only inspection; mutations disabled"],
        ["GitHub", "Official GitHub MCP", "Selected repositories and read-only toolsets"],
        ["Documents", "Microsoft MarkItDown", "Local sandboxed conversion; plugins disabled"],
        ["Developer docs", "Context7", "Public queries; no private code or secrets"],
        ["Search", "Brave Search MCP", "Redacted queries; adversarial result labels"],
        ["AI ecosystem", "Hugging Face MCP", "Search/read only; no jobs or dynamic Spaces"],
        ["Time", "MCP Time", "Read-only"],
        ["Windows", "Custom signed C# broker", "Allowlisted app/window/media/UIA capabilities"],
    ], [1700, 3200, 4000])
    d.heading("7.9 Tool effectiveness metrics", 2)
    d.table(["Metric", "Use"], [
        ["Selection precision", "Was the selected tool appropriate for the task?"],
        ["Verified success rate", "Fraction of calls whose postconditions were proven"],
        ["Policy-denial rate", "Detect poor retrieval/planning or overly broad requests"],
        ["Argument correction rate", "Measure schema clarity and planner quality"],
        ["Latency/cost percentiles", "Route among approved equivalents"],
        ["Uncertain outcome rate", "Prioritize better verification or deprecate tools"],
        ["Contract drift events", "Detect supply-chain and update risk"],
    ], [2500, 6400])

    # 8 Guardrails
    d.heading("8. Jarvis guardrail and policy architecture — separate architecture", 1)
    d.heading("8.1 Security principle", 2)
    add_narrative(d, [
        "Guardrails are not a prompt, a refusal model or a content filter. Jarvis uses policy reasoning plus operating-system containment. Soft filters can improve conversation quality, but only deterministic policy, scoped authority and Windows enforcement can constrain effects after the model or a tool misbehaves.",
        "The control plane implements the standard PAP/PDP/PEP/PIP structure. The Policy Administration Point manages reviewed Rego bundles. OPA is the Policy Decision Point. Every action crosses the Policy Enforcement Point in the gateway and broker. Policy Information Points supply identity, app, publisher, resource, data label, destination, risk, budget and environment facts."
    ])
    d.code("USER / ADMIN → PAP → signed policy bundle → OPA PDP\n"
           "                                      ▲\n"
           "IDENTITY / RESOURCE / RISK / DEVICE ─ PIP\n"
           "                                      │\n"
           "LANGGRAPH ActionIntent → PEP ─────────┤\n"
           "                         │             │\n"
           "TRUSTED APPROVAL UI ─────┘             │\n"
           "                         ▼             │\n"
           "                 scoped decision/grant\n"
           "                         ▼\n"
           "          MCP RUNTIME / WINDOWS BROKER / VERIFIER")
    d.heading("8.2 Three enforcement rings", 2)
    d.table(["Ring", "Scope", "Examples"], [
        ["Ring 0: immutable", "Compiled/signed restrictions unavailable to conversation", "No credential extraction, hidden capture, policy disabling, security bypass or mass destructive behavior"],
        ["Ring 1: policy as code", "OPA decisions and obligations", "App/site/resource scope, approvals, destinations, labels, budgets and reversibility"],
        ["Ring 2: OS containment", "Windows and container enforcement", "Restricted tokens, MIC, ACLs, Job Objects, egress, WDAC, JEA, Sandbox and UAC"],
    ], [1900, 2800, 4200])
    d.heading("8.3 Policy hierarchy", 2)
    for idx, x in enumerate([
        "Immutable root safety restrictions",
        "Device and Windows enterprise policy",
        "Owner privacy and data-release policy",
        "Application, account and resource policy",
        "Session permission",
        "Task-specific grant",
        "Tool-declared limitation"
    ], 1):
        d.numbered(str(idx), x)
    d.paragraph("Deny always wins. A lower layer cannot broaden a higher layer. A tool contract can be stricter than policy, never more permissive.")

    d.heading("8.4 Approval architecture", 2)
    add_narrative(d, [
        "Approvals show the exact operation, canonical target, recipient/destination, data being released, diff or message preview, financial/privacy impact and reversibility. They expire, are nonce-bound and are valid only for the previewed intent. A model-generated confirm flag, character animation or MCP parameter is never approval.",
        "R3 approval is one-shot and may require Windows Hello. Session approvals are limited to a named capability, resource scope, maximum count and expiry; they do not cover changed destinations or elevated actions."
    ])
    d.heading("8.5 Windows enforcement", 2)
    d.table(["Primitive", "Application"], [
        ["Restricted access token", "Remove unnecessary SIDs and privileges from workers"],
        ["Mandatory Integrity Control", "Run untrusted workers at low integrity where compatible"],
        ["Job Objects", "Limit CPU, memory, process count and child processes; terminate on revocation"],
        ["NTFS ACL/canonical paths", "Enforce approved roots and prevent traversal or junction escape"],
        ["Windows Firewall", "Deny egress by default and allow exact destinations"],
        ["WDAC/application control", "Allow only signed/pinned executables for trusted components"],
        ["JEA", "Expose only narrowly defined administrative PowerShell operations"],
        ["Windows Sandbox", "Evaluate installers, documents and experimental MCP servers"],
        ["DPAPI/Credential Manager", "Store secrets outside prompts, state and environment dumps"],
    ], [2400, 6500])
    d.heading("8.6 Prompt-injection and confused-deputy defenses", 2)
    for x in [
        "Treat websites, emails, documents, tool descriptions and tool results as untrusted data.",
        "Preserve provenance and taint labels through summaries and transformations.",
        "Separate user goal/control flow from observed content; observed text cannot grant authority.",
        "Recheck task alignment and destination before every consequential action.",
        "Never place policy, approval, secret-store or audit-administration interfaces behind MCP tools.",
        "Require a new decision when recipients, origins, attachments or resource scope change.",
        "Limit context size and strip hidden markup to reduce context flooding, while relying on policy for safety."
    ]:
        d.bullet(x)
    d.heading("8.7 MCP-specific guardrails", 2)
    for x in [
        "Allowlisted publishers/repositories, exact versions and executable/container digests.",
        "SBOM, vulnerability/configuration scans and adversarial tests before promotion.",
        "No token passthrough; per-server scoped credentials and correct OAuth audience/PKCE handling.",
        "Read-only mounts by default, canonical path checks and reparse-point defenses.",
        "Network egress policy and SSRF blocking, including cloud metadata endpoints.",
        "Schema/description drift detection with automatic quarantine.",
        "Output size, timeout and rate limits; tool output cannot request more permission."
    ]:
        d.bullet(x)
    d.heading("8.8 Privacy guardrails", 2)
    add_narrative(d, [
        "Excluded apps are identified using signed executable path and publisher, not only process name. Password managers, password fields, banking apps, private browser windows and secure desktop force Private handling. Screen regions and sites can be user-excluded. Screen/audio buffers are short-lived and never archived by default. A permanent visible indicator shows active screen, microphone or camera observation.",
        "Permissions are intentionally separate: may-see does not imply may-send; may-use-for-task does not imply may-remember. Deletion propagates to relational records, vector indexes, caches and derived summaries according to a deletion ledger."
    ])
    d.heading("8.9 Incident response", 2)
    d.code("Detect anomaly → revoke desktop lease and capability grants → cancel workers\n"
           "→ isolate/quarantine tool → preserve redacted evidence → notify user\n"
           "→ rotate scoped secret if exposure is possible → investigate trace/audit chain\n"
           "→ patch policy/contract → regression test → reviewed restoration")
    d.heading("8.10 Example policy decision", 2)
    d.code('{\n'
           '  "decision": "ASK_USER",\n'
           '  "risk": "R2",\n'
           '  "reason_codes": ["LOCAL_FILE_MUTATION"],\n'
           '  "obligations": ["SHOW_DIFF", "CREATE_BACKUP", "VERIFY_HASH"],\n'
           '  "approval_scope": {"resource": "C:/Users/.../notes.txt", "calls": 1},\n'
           '  "expires_in_seconds": 120\n'
           '}')

    # 9 Character
    d.heading("9. Character and desktop embodiment architecture", 1)
    d.heading("9.1 Asset pipeline", 2)
    d.code("Reference images → orthographic cleanup → Blender base mesh/sculpt\n"
           "→ retopology/UV/PBR textures → humanoid + facial rig → accessory rigs\n"
           "→ walk/run/idle/listen/talk gesture library → VRM/glTF export\n"
           "→ Godot import, shader validation and desktop-scale LOD testing")
    d.heading("9.2 Godot overlay", 2)
    add_narrative(d, [
        "Godot renders a transparent, borderless, always-on-top window positioned in a configurable strip above the taskbar. The overlay supports multiple monitors, DPI scaling, click-through outside interactive character regions, work-area changes and avoidance of menus or notifications. It does not modify Explorer or the taskbar itself.",
        "The scene separates CharacterBody/navigation, animation tree, gaze target, lip-sync, gesture layer, accessory physics, speech bubble and status indicator. IPC carries only semantic state and user interactions. A local state controller smooths transitions so model latency cannot freeze or jerk the avatar."
    ])
    d.heading("9.3 Animation requirements", 2)
    d.table(["Layer", "Examples"], [
        ["Locomotion", "Idle, walk, run, turn, stop, sit/lean where supported"],
        ["Conversation", "Listen, think, speak, acknowledge, interrupt and wait"],
        ["Emotion", "Neutral, curious, pleased, concerned and apologetic at bounded intensity"],
        ["Gaze", "User/cursor, active window, notification or neutral roaming"],
        ["Facial", "Visemes, jaw, cheeks, brows and subtle head motion; sunglasses retained"],
        ["Secondary", "Hair, shirt, bag, lanyard and earphone-cable motion with stability limits"],
        ["Safety", "Visible private/sleep/blocked states that override personality animation"],
    ], [1900, 7000])

    # 10 observability
    d.heading("10. OpenTelemetry, audit and review architecture", 1)
    d.heading("10.1 Two complementary records", 2)
    add_narrative(d, [
        "OpenTelemetry is the operational observability fabric, not the sole security record. It produces and transports traces, logs and metrics to backends. The append-only audit journal is the authoritative history of security-relevant actions. Both share task_id and trace_id so an operator can move from a concise audit event to the complete operational timeline.",
        "The audit journal is hash-chained and access-controlled. OpenTelemetry data is optimized for debugging, performance and dashboards and may have shorter retention. Neither system stores passwords, API keys, authentication cookies, raw private-screen content or unrestricted prompt payloads."
    ])
    d.code("Jarvis services → OpenTelemetry SDKs → local OTel Collector\n"
           "                         ├→ Tempo (traces)\n"
           "                         ├→ Loki (redacted logs)\n"
           "                         ├→ Prometheus (metrics)\n"
           "                         └→ Grafana (review dashboards)\n"
           "Policy/Tool/Verifier ─────────→ append-only audit writer/store")
    d.heading("10.2 Trace model", 2)
    d.table(["Span", "Required attributes"], [
        ["jarvis.task", "task_id, session_id, input mode, final status"],
        ["privacy.context_release", "source class, labels, redaction count, destination profile"],
        ["llm.request", "provider profile, model, latency, tokens, cost; no secret/raw private content"],
        ["policy.evaluate", "intent digest, risk, decision, obligations and policy bundle version"],
        ["approval.wait", "approval type, expiry and outcome; no biometric material"],
        ["tool.execute", "tool ID/digest, operation, latency, normalized status and idempotency key"],
        ["windows.action", "broker version, capability, target identity and result"],
        ["verify.postcondition", "verifier type, predicate count and VERIFIED/FAILED/UNCERTAIN"],
        ["memory.admission", "class, labels, provenance type, decision and retention"],
    ], [2300, 6600])
    d.heading("10.3 Authoritative audit event", 2)
    d.code('{\n'
           '  "event_id": "uuid", "previous_hash": "...", "event_hash": "...",\n'
           '  "time": "UTC", "task_id": "...", "trace_id": "...",\n'
           '  "actor": "user|jarvis|tool", "action": "file.write",\n'
           '  "resource_digest": "...", "destination": "LOCAL_DEVICE",\n'
           '  "policy": {"bundle": "...", "decision": "ALLOW", "risk": "R2"},\n'
           '  "approval_id": "...", "tool_digest": "...",\n'
           '  "result": "VERIFIED", "evidence_refs": []\n'
           '}')
    d.heading("10.4 Dashboards", 2)
    for x in [
        "Task timeline: request → plan → decision → approval → tool → verification → memory.",
        "Tool health: success, uncertainty, latency, circuit breaker and schema drift.",
        "Security: denials, approval patterns, prohibited access attempts and quarantines.",
        "Privacy: context release by label/provider, redaction counts and private-mode activations.",
        "Cost/performance: model tokens, endpoint latency, speech latency and resource usage.",
        "User review: searchable action history with exact targets, outcome and evidence references."
    ]:
        d.bullet(x)
    d.heading("10.5 Retention and privacy", 2)
    add_narrative(d, [
        "Retention is policy-driven by data class and record purpose. Metrics can be long-lived because they contain no content. Detailed traces have shorter retention. Security audit retention is longer but stores identifiers, hashes and redacted summaries rather than private bodies. The user can export and review their action history; privacy deletion applies where legally and technically permitted without destroying the integrity of unrelated hash-chain evidence."
    ])

    # 11 data/memory
    d.heading("11. Data, state and memory architecture", 1)
    d.table(["Store", "Contents", "Technology direction"], [
        ["Graph checkpoints", "LangGraph task state, interrupts and idempotency references", "PostgreSQL-backed durable saver"],
        ["Operational DB", "Users, policies metadata, tool catalog, tasks and approvals", "PostgreSQL"],
        ["Vector index", "Permitted semantic memory embeddings", "pgvector"],
        ["Audit journal", "Append-only security events and evidence references", "Encrypted append-only DB/object segments"],
        ["Telemetry", "Traces, logs and metrics", "Tempo/Loki/Prometheus"],
        ["Secrets", "API keys, OAuth refresh tokens and broker secrets", "Credential Manager/DPAPI"],
        ["Quarantine", "Untrusted downloads, extracted claims and experimental packages", "Restricted local store with expiry"],
    ], [2100, 4200, 2700])
    d.heading("11.1 Memory classes", 2)
    d.table(["Class", "Purpose", "Admission rule"], [
        ["Working", "Current conversation and execution", "Task-scoped; short retention"],
        ["Episodic", "Completed activities and outcomes", "Policy/consent, provenance and expiry"],
        ["Semantic", "Stable user preferences and facts", "Confidence, contradiction and sensitivity checks"],
        ["Procedural", "Approved reusable workflows", "Versioned, tested, reviewed and signed"],
        ["Relationship", "Names and interaction preferences", "Editable, scoped and opt-in where sensitive"],
        ["Quarantine", "Unvalidated claims from untrusted content", "Cannot drive action or procedural memory"],
    ], [1700, 3900, 3300])
    d.heading("11.2 Core identifiers", 2)
    add_narrative(d, [
        "task_id identifies the user objective; trace_id identifies distributed operational work; intent_id identifies one proposed consequential action; approval_id identifies a trusted approval event; grant_id identifies issued authority; idempotency_key identifies one logical effect; audit_event_id identifies immutable evidence. These identifiers are propagated explicitly rather than inferred from timestamps."
    ])

    # 12 testing
    d.heading("12. Verification, testing and evaluation", 1)
    d.heading("12.1 Test layers", 2)
    d.table(["Layer", "Tests"], [
        ["Contracts", "JSON Schema compatibility, canonicalization, grant signature and result envelope"],
        ["Tanglish decoder", "Clean oracle text, corrupted STT, marker preservation, evidence binding, abstention, determinism and latency"],
        ["Policy", "Allow/deny/ask matrices, obligations, deny precedence and policy mutation protection"],
        ["Tools", "Schema fuzzing, timeouts, cancellation, output limits, contract drift and sandbox escapes"],
        ["Agent", "Plan quality, tool selection, bounded loops, checkpoint recovery and uncertainty handling"],
        ["Privacy", "Excluded apps, secret patterns, release labels, deletion propagation and telemetry leakage"],
        ["Desktop", "DPI, multi-monitor, focus races, changed layouts, user takeover and stale UI targets"],
        ["Security", "Prompt injection, confused deputy, SSRF, poisoned memory and compromised MCP scenarios"],
        ["Experience", "Voice latency, false wake, barge-in, animation responsiveness and interruption rate"],
        ["End-to-end", "Clean VM initialization, task execution, evidence-based assertion and restoration"],
    ], [1900, 7000])
    d.heading("12.2 Primary evaluation metrics", 2)
    for x in [
        "Verified task completion and subtask correctness.",
        "Tanglish strict semantic success, intent/slot/referent accuracy and correct-clarification rate.",
        "Critical-marker recall and fabricated-entity rate—the latter targets zero.",
        "Semantic-decoder warm latency, generated tokens, peak RSS, paging and 100-request stability.",
        "Unauthorized action rate and private-information leakage rate—both target zero.",
        "Uncertain-result rate, recovery quality and duplicate-effect rate.",
        "Prompt-injection success rate under AgentDojo-like scenarios.",
        "Memory falsehood, contradiction and poisoning rates.",
        "Tool-selection precision, policy-denial waste and schema correction rate.",
        "Voice first-response latency, false wake rate and barge-in response time.",
        "Character frame time, overlay input correctness and multi-monitor stability.",
        "Model/tool cost per verified task and total action count."
    ]:
        d.bullet(x)
    d.heading("12.3 Release gates", 2)
    add_narrative(d, [
        "Capabilities advance from laboratory to shadow, supervised, limited production and trusted-routine status. Promotion requires contract completeness, security review, stable verification, rollback/uncertainty behavior, telemetry coverage and a passing adversarial suite. A capability is demoted automatically on unexpected digest/schema change or severe verification failure."
    ])

    # 13 Plan
    d.heading("13. Final implementation plan", 1)
    d.heading("13.1 Delivery strategy", 2)
    add_narrative(d, [
        "Delivery is organized as eighteen indicative two-week sprints beginning with architecture and security foundations. Powerful capabilities arrive only after policy, approval, audit and verification exist. The Excel workbook provides story-level scope, points, dependencies, owner roles, risks and acceptance gates.",
        "Each sprint produces an integrated demonstrable increment. Documentation, threat modeling, tests, telemetry and rollback are part of the work rather than cleanup activities. Sprint 0 recalibrates dates and velocity."
    ])
    sprint_rows = [
        ["S0", "Architecture baseline", "ADRs, threat model, repo, contracts and development environments"],
        ["S1", "Contracts and identity", "Task/intent/grant/result schemas, signing identities and IPC skeleton"],
        ["S2", "Policy core", "OPA service, immutable restrictions, risk engine and policy test harness"],
        ["S3", "Approval and evidence", "Trusted approval UI, emergency stop, append-only audit and OTel baseline"],
        ["S4", "Cognitive runtime", "Controlled Tanglish decoder, intent gate/router, LangGraph skeleton and primary-model gateway"],
        ["S5", "Safe Windows broker", "App/window/media capabilities, restricted process and desktop lease"],
        ["S6", "Verification/recovery", "Independent evidence, idempotency, compensation and uncertainty handling"],
        ["S7", "Privacy/perception", "UIA metadata, exclusions, labeling, redaction and private mode"],
        ["S8", "Tool platform core", "Catalog, contracts, semantic retrieval, grants, normalization and runtime"],
        ["S9", "Initial MCP pack", "Playwright, Filesystem, Git, MarkItDown, Search and Time in restricted modes"],
        ["S10", "Voice", "Wake/VAD/STT/TTS, echo cancellation, barge-in and latency telemetry"],
        ["S11", "Character", "3D MVP, Godot overlay, state machine, lip-sync and multi-monitor behavior"],
        ["S12", "Controlled memory", "Memory classes, admission/retrieval, provenance, retention and deletion"],
        ["S13", "Integrated workflows", "Research, documents, browser and development read workflows"],
        ["S14", "Supervised desktop", "Safe UIA interaction, previews, user takeover and workflow drafts"],
        ["S15", "Proactivity", "Approved deterministic triggers, budgets, explanations and quiet hours"],
        ["S16", "Hardening", "Adversarial security, privacy, reliability, performance and disaster recovery"],
        ["S17", "Beta/release", "Installer, signed updates, dashboards, documentation, pilot and release gates"],
    ]
    d.table(["Sprint", "Theme", "Outcome"], sprint_rows, [800, 2400, 5700])
    d.heading("13.2 MVP capability boundary", 2)
    add_narrative(d, [
        "The MVP includes conversation, voice, the character, app launch/focus, permitted window metadata, volume/media, safe browser research, local document conversion, scoped read-only file/Git/GitHub operations, controlled memory, policy/approval, verification, audit and telemetry. It excludes unrestricted shell/PowerShell, silent keyboard/mouse control, software installation, purchases, permanent deletion, autonomous message sending and broad account profiles.",
        "After beta evidence meets release gates, mutations are introduced one workflow at a time. Each gains a new tool contract, policy matrix, approval experience, verification predicate and regression suite."
    ])
    d.heading("13.3 Targeted validation spikes", 2)
    for x in [
        "ToolHive behavior and networking on the selected Windows/Docker/WSL configuration.",
        "Godot transparent overlay, click-through regions, DPI and multi-monitor behavior.",
        "C# UI Automation reliability across the first approved applications.",
        "OPA decision latency and signed capability verification over named pipes.",
        "Smaller Tanglish semantic-decoder accuracy, no-thinking compliance, warm latency and memory on the target laptop; Qwen3-8B Q4 is rejected evidence.",
        "Direct-primary versus certified-decoder-plus-primary comparison to prove the extra model earns its latency.",
        "Candidate LLM endpoint structured-output/tool-planning behavior under redacted context.",
        "Local STT/TTS latency, quality and memory use on Ryzen 5 7520U/16 GB target hardware.",
        "Python 3.12.10 dependency compatibility for speech, LangGraph and observability packages.",
        "MCP license, release, dependency and digest review at implementation time."
    ]:
        d.bullet(x)

    # 14 acceptance
    d.heading("14. Acceptance criteria and definition of done", 1)
    d.heading("14.1 System acceptance", 2)
    for x in [
        "STT evidence is never treated as an authoritative command, and every model-selected critical slot is bound to supplied evidence.",
        "The Tanglish decoder produces no prose or chain-of-thought, fabricates no critical entity and clarifies missing or ambiguous targets.",
        "No consequential action bypasses ActionIntent, policy, capability validation or audit.",
        "R3 actions cannot execute without an exact unexpired trusted approval.",
        "Private-mode and exclusion policies prevent capture before model/tool release.",
        "Credentials never appear in prompts, LangGraph state, MCP output, telemetry or audit summaries.",
        "Every effectful production capability has independent postcondition verification.",
        "User takeover and emergency stop revoke actuation within the specified latency objective.",
        "A crash/restart does not duplicate a committed external effect.",
        "Tool/schema/digest drift results in quarantine, not silent adoption.",
        "The user can review a task from request through policy, action, evidence and memory changes.",
        "The character stays responsive and communicates listening, thinking, approval, execution and private states."
    ]:
        d.bullet(x)
    d.heading("14.2 Story-level definition of done", 2)
    for x in [
        "Code reviewed, formatted and covered by appropriate unit/contract/integration tests.",
        "Threat and privacy impacts reviewed for changed data flows or capabilities.",
        "Schemas and ADRs updated; backward compatibility or migration documented.",
        "OpenTelemetry spans/metrics added with sensitive-field tests.",
        "Audit events added for security-relevant decisions/effects.",
        "Failure, cancellation, timeout and recovery paths tested.",
        "User-visible behavior and accessibility documented.",
        "Acceptance criteria demonstrated in a clean test environment."
    ]:
        d.bullet(x)

    # 15 appendices
    d.heading("15. Appendices", 1)
    d.heading("15.1 Suggested repository structure", 2)
    d.code("jarvis/\n"
           "├─ apps/{avatar,approval-ui,settings-ui,audit-review}\n"
           "├─ services/{orchestrator,interaction,tanglish-decoder,intent-router,perception}\n"
           "│          {privacy-firewall,llm-gateway,policy-gateway,tool-platform,verifier,memory}\n"
           "├─ native/{windows-broker,privileged-broker}\n"
           "├─ packages/{contracts,event-models,tool-sdk,policy-client,telemetry}\n"
           "├─ policies/{immutable,privacy,windows,tools,user}\n"
           "├─ mcp/{manifests,pinned-schemas,sandbox-profiles}\n"
           "├─ graphs/{conversation,desktop,browser,files,recovery,memory}\n"
           "├─ tests/{unit,contract,integration,security,fixtures}\n"
           "├─ deliverables/{architecture,plans,decisions,research,reports,checkpoints,manifests}\n"
           "├─ assets/character-references\n"
           "├─ tools/  # generators and developer utilities\n"
           "├─ storage/{engines,models,datasets,benchmarks,cache,temp}  # local, Git-ignored\n"
           "└─ infrastructure/{containers,telemetry,database,signing}")
    d.heading("15.2 ActionIntent example", 2)
    d.code('{\n'
           '  "task_id": "task-123",\n'
           '  "action": "file.write",\n'
           '  "resource": "C:/Users/owner/Documents/notes.txt",\n'
           '  "purpose": "Save the approved meeting summary",\n'
           '  "data_labels": ["PERSONAL"],\n'
           '  "destination": "LOCAL_DEVICE",\n'
           '  "reversible": true,\n'
           '  "expected_effect": {"operation": "replace", "bytes_changed_max": 2000},\n'
           '  "verification": {"type": "hash_and_diff"}\n'
           '}')
    d.heading("15.3 Key references used in the design", 2)
    refs = [
        "LangGraph documentation: persistence, durable execution and human interrupts.",
        "Microsoft Windows UI Automation, restricted tokens, Mandatory Integrity Control, Job Objects, AppContainer, DPAPI, WDAC, JEA and Windows Sandbox documentation.",
        "Model Context Protocol security, authorization, local server and client best-practice guidance.",
        "NIST AI RMF and NIST Generative AI Profile; OWASP LLM and Agentic Top 10; MITRE ATLAS; Google SAIF.",
        "Research: ReAct, Reflexion, Toolformer, Generative Agents, MemGPT, Mind2Web, OSWorld, Windows Agent Arena, WebArena, AgentDojo, CaMeL, ToolEmu and Whisper.",
        "Open-source candidates: OPA, Presidio, ToolHive, Docker MCP Gateway, MCP Inspector, Agent Scan, PyRIT, garak and promptfoo."
    ]
    for x in refs:
        d.bullet(x)
    d.heading("15.4 Glossary", 2)
    d.table(["Term", "Meaning"], [
        ["ActionIntent", "Typed proposal describing one intended consequential effect"],
        ["TranscriptEvidence", "Untrusted STT hypotheses, quality signals and source-bound candidates"],
        ["IntentEnvelope", "Validated semantic interpretation with no execution authority"],
        ["Tanglish decoder", "Bounded local semantic compiler; never an assistant, planner or policy authority"],
        ["Capability grant", "Signed, narrow, expiring authority for an exact operation"],
        ["MCP", "Model Context Protocol for interoperable tools/resources/prompts"],
        ["PAP/PDP/PEP/PIP", "Policy administration, decision, enforcement and information points"],
        ["UIA", "Microsoft Windows UI Automation accessibility framework"],
        ["Idempotency", "Property allowing safe repetition without duplicating the logical effect"],
        ["Postcondition", "Observable predicate proving the requested effect occurred"],
        ["Taint/provenance", "Origin and trust metadata preserved with external content"],
        ["OTel", "OpenTelemetry: vendor-neutral traces, logs and metrics instrumentation"],
    ], [2100, 6800])

    d.finish(footer_rid)

    rels = ET.Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    for rid, typ, target in d.relationships:
        ET.SubElement(rels, "Relationship", {"Id": rid, "Type": typ, "Target": target})

    root_rels = ET.Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    ET.SubElement(root_rels, "Relationship", {
        "Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
        "Target": "word/document.xml"})
    ET.SubElement(root_rels, "Relationship", {
        "Id": "rId2", "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
        "Target": "docProps/core.xml"})
    ET.SubElement(root_rels, "Relationship", {
        "Id": "rId3", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties",
        "Target": "docProps/app.xml"})

    ct = ET.Element("Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types")
    ET.SubElement(ct, "Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    ET.SubElement(ct, "Default", {"Extension": "xml", "ContentType": "application/xml"})
    ET.SubElement(ct, "Default", {"Extension": "jpg", "ContentType": "image/jpeg"})
    ET.SubElement(ct, "Override", {"PartName": "/word/document.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"})
    ET.SubElement(ct, "Override", {"PartName": "/word/styles.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"})
    ET.SubElement(ct, "Override", {"PartName": "/word/footer1.xml", "ContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"})
    ET.SubElement(ct, "Override", {"PartName": "/docProps/core.xml", "ContentType": "application/vnd.openxmlformats-package.core-properties+xml"})
    ET.SubElement(ct, "Override", {"PartName": "/docProps/app.xml", "ContentType": "application/vnd.openxmlformats-officedocument.extended-properties+xml"})

    core = ET.Element(qn(CP, "coreProperties"))
    ET.SubElement(core, qn(DC, "title")).text = "Jarvis Architecture and Implementation Plan"
    ET.SubElement(core, qn(DC, "subject")).text = "Personal AI companion, tool harness and guardrail architecture"
    ET.SubElement(core, qn(DC, "creator")).text = "Jarvis Project"
    ET.SubElement(core, qn(CP, "keywords")).text = "Jarvis, LangGraph, MCP, OPA, Windows, OpenTelemetry"
    created = ET.SubElement(core, qn(DCTERMS, "created"), {qn(XSI, "type"): "dcterms:W3CDTF"})
    created.text = "2026-10-08T00:00:00Z"

    app = ET.Element("Properties", xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
                     attrib={"xmlns:vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"})
    ET.SubElement(app, "Application").text = "Jarvis Document Generator"
    ET.SubElement(app, "Company").text = "Jarvis Project"

    with zipfile.ZipFile(DOCX_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", xml_bytes(ct))
        z.writestr("_rels/.rels", xml_bytes(root_rels))
        z.writestr("word/document.xml", xml_bytes(d.document))
        z.writestr("word/styles.xml", styles_xml())
        z.writestr("word/footer1.xml", footer_xml())
        z.writestr("word/_rels/document.xml.rels", xml_bytes(rels))
        z.writestr("docProps/core.xml", xml_bytes(core))
        z.writestr("docProps/app.xml", xml_bytes(app))
        if IMAGE_PORTRAIT.exists():
            z.write(IMAGE_PORTRAIT, "word/media/image1.jpg")
        if IMAGE_TURNAROUND.exists():
            z.write(IMAGE_TURNAROUND, f"word/media/image{2 if IMAGE_PORTRAIT.exists() else 1}.jpg")


# ------------------------- XLSX generation -------------------------

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
XR = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("", X)
ET.register_namespace("r", XR)


def excel_col(n: int) -> str:
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def excel_date(d: date) -> int:
    return (d - date(1899, 12, 30)).days


class Sheet:
    def __init__(self, name: str, headers: list[str], widths: list[float], *, freeze: str = "A2") -> None:
        self.name = name
        self.headers = headers
        self.widths = widths
        self.freeze = freeze
        self.rows: list[list[object]] = []
        self.row_styles: list[list[int] | None] = []
        self.formulas: dict[tuple[int, int], str] = {}

    def add(self, row: list[object], styles: list[int] | None = None) -> None:
        self.rows.append(row)
        self.row_styles.append(styles)

    def formula(self, row: int, col: int, formula: str) -> None:
        self.formulas[(row, col)] = formula

    def xml(self) -> bytes:
        ws = ET.Element(qn(X, "worksheet"))
        end = f"{excel_col(len(self.headers))}{len(self.rows) + 1}"
        ET.SubElement(ws, qn(X, "dimension"), {"ref": f"A1:{end}"})
        views = ET.SubElement(ws, qn(X, "sheetViews"))
        sv = ET.SubElement(views, qn(X, "sheetView"), {"workbookViewId": "0"})
        if self.freeze:
            row = int("".join(c for c in self.freeze if c.isdigit()) or "1")
            col_letters = "".join(c for c in self.freeze if c.isalpha())
            col_num = 0
            for c in col_letters:
                col_num = col_num * 26 + ord(c.upper()) - 64
            if row > 1 and col_num > 1:
                active_pane = "bottomRight"
            elif row > 1:
                active_pane = "bottomLeft"
            else:
                active_pane = "topRight"
            attrs = {"state": "frozen", "topLeftCell": self.freeze, "activePane": active_pane}
            if row > 1:
                attrs["ySplit"] = str(row - 1)
            if col_num > 1:
                attrs["xSplit"] = str(col_num - 1)
            ET.SubElement(sv, qn(X, "pane"), attrs)
            ET.SubElement(sv, qn(X, "selection"), {
                "pane": active_pane, "activeCell": self.freeze, "sqref": self.freeze})
        ET.SubElement(ws, qn(X, "sheetFormatPr"), {"defaultRowHeight": "18"})
        cols = ET.SubElement(ws, qn(X, "cols"))
        for idx, width in enumerate(self.widths, 1):
            ET.SubElement(cols, qn(X, "col"), {"min": str(idx), "max": str(idx), "width": str(width), "customWidth": "1"})
        data = ET.SubElement(ws, qn(X, "sheetData"))
        all_rows = [self.headers] + self.rows
        for ridx, row in enumerate(all_rows, 1):
            rr = ET.SubElement(data, qn(X, "row"), {"r": str(ridx), "ht": "30" if ridx == 1 else "36", "customHeight": "1"})
            for cidx, value in enumerate(row, 1):
                ref = f"{excel_col(cidx)}{ridx}"
                style = 2 if ridx == 1 else 3
                if ridx > 1 and self.row_styles[ridx - 2] and cidx <= len(self.row_styles[ridx - 2]):
                    style = self.row_styles[ridx - 2][cidx - 1]
                formula = self.formulas.get((ridx, cidx))
                if formula:
                    c = ET.SubElement(rr, qn(X, "c"), {"r": ref, "s": str(style)})
                    ET.SubElement(c, qn(X, "f")).text = formula
                    ET.SubElement(c, qn(X, "v")).text = "0"
                    continue
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    c = ET.SubElement(rr, qn(X, "c"), {"r": ref, "s": str(style), "t": "n"})
                    ET.SubElement(c, qn(X, "v")).text = str(value)
                else:
                    c = ET.SubElement(rr, qn(X, "c"), {"r": ref, "s": str(style), "t": "inlineStr"})
                    isel = ET.SubElement(c, qn(X, "is"))
                    ET.SubElement(isel, qn(X, "t"), {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}).text = str(value)
        ET.SubElement(ws, qn(X, "autoFilter"), {"ref": f"A1:{end}"})
        ET.SubElement(ws, qn(X, "pageMargins"), {"left": "0.25", "right": "0.25", "top": "0.5", "bottom": "0.5", "header": "0.2", "footer": "0.2"})
        ET.SubElement(ws, qn(X, "pageSetup"), {"orientation": "landscape", "fitToWidth": "1", "fitToHeight": "0"})
        return xml_bytes(ws)


def xlsx_styles() -> bytes:
    st = ET.Element(qn(X, "styleSheet"))
    fonts = ET.SubElement(st, qn(X, "fonts"), {"count": "3"})
    f0 = ET.SubElement(fonts, qn(X, "font")); ET.SubElement(f0, qn(X, "sz"), {"val": "10"}); ET.SubElement(f0, qn(X, "name"), {"val": "Aptos"})
    f1 = ET.SubElement(fonts, qn(X, "font")); ET.SubElement(f1, qn(X, "b")); ET.SubElement(f1, qn(X, "sz"), {"val": "10"}); ET.SubElement(f1, qn(X, "color"), {"rgb": "FFFFFFFF"}); ET.SubElement(f1, qn(X, "name"), {"val": "Aptos"})
    f2 = ET.SubElement(fonts, qn(X, "font")); ET.SubElement(f2, qn(X, "b")); ET.SubElement(f2, qn(X, "sz"), {"val": "10"}); ET.SubElement(f2, qn(X, "color"), {"rgb": "FF16324F"}); ET.SubElement(f2, qn(X, "name"), {"val": "Aptos"})
    fills = ET.SubElement(st, qn(X, "fills"), {"count": "8"})
    for pattern, color in [("none", None), ("gray125", None), ("solid", "FF16324F"), ("solid", "FFEAF2F4"), ("solid", "FFFFF2CC"), ("solid", "FFE2F0D9"), ("solid", "FFFCE4D6"), ("solid", "FFF4CCCC")]:
        fill = ET.SubElement(fills, qn(X, "fill")); pf = ET.SubElement(fill, qn(X, "patternFill"), {"patternType": pattern})
        if color:
            ET.SubElement(pf, qn(X, "fgColor"), {"rgb": color}); ET.SubElement(pf, qn(X, "bgColor"), {"indexed": "64"})
    borders = ET.SubElement(st, qn(X, "borders"), {"count": "2"})
    b0 = ET.SubElement(borders, qn(X, "border"))
    for side in ["left", "right", "top", "bottom", "diagonal"]: ET.SubElement(b0, qn(X, side))
    b1 = ET.SubElement(borders, qn(X, "border"))
    for side in ["left", "right", "top", "bottom"]:
        s = ET.SubElement(b1, qn(X, side), {"style": "thin"}); ET.SubElement(s, qn(X, "color"), {"rgb": "FFD9E1E5"})
    ET.SubElement(b1, qn(X, "diagonal"))
    csxfs = ET.SubElement(st, qn(X, "cellStyleXfs"), {"count": "1"}); ET.SubElement(csxfs, qn(X, "xf"), {"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0"})
    xfs = ET.SubElement(st, qn(X, "cellXfs"), {"count": "11"})
    def xf(font=0, fill=0, border=1, num=0, align=True):
        e = ET.SubElement(xfs, qn(X, "xf"), {"numFmtId": str(num), "fontId": str(font), "fillId": str(fill), "borderId": str(border), "xfId": "0", "applyAlignment": "1"})
        if align: ET.SubElement(e, qn(X, "alignment"), {"vertical": "top", "wrapText": "1"})
    xf(border=0)                 # 0 default
    xf(font=2, fill=3)           # 1 title-ish
    xf(font=1, fill=2)           # 2 header
    xf()                          # 3 body
    xf(num=14)                    # 4 date
    xf(fill=4)                    # 5 planned/yellow
    xf(fill=5)                    # 6 done/green
    xf(fill=6)                    # 7 active/orange
    xf(fill=7)                    # 8 high risk/red
    xf(font=2, fill=3)            # 9 group/blue light
    xf(num=0)                     # 10 numeric
    styles = ET.SubElement(st, qn(X, "cellStyles"), {"count": "1"})
    ET.SubElement(styles, qn(X, "cellStyle"), {"name": "Normal", "xfId": "0", "builtinId": "0"})
    ET.SubElement(st, qn(X, "dxfs"), {"count": "0"})
    ET.SubElement(st, qn(X, "tableStyles"), {"count": "0", "defaultTableStyle": "TableStyleMedium2", "defaultPivotStyle": "PivotStyleLight16"})
    return xml_bytes(st)


SPRINTS = [
    ("S0", "Architecture Baseline", "Freeze scope, risks, contracts and environments", "Architecture", "Planned"),
    ("S1", "Contracts and Identity", "Schemas, signing identities and IPC skeleton", "Platform", "Planned"),
    ("S2", "Policy Core", "OPA, immutable policy, risk and tests", "Security", "Planned"),
    ("S3", "Approval and Evidence", "Trusted approval, stop, audit and telemetry", "Security", "Planned"),
    ("S4", "Cognitive Runtime", "LangGraph, model gateway and checkpoints", "Agent", "Planned"),
    ("S5", "Safe Windows Broker", "App/window/media capabilities and leases", "Windows", "Planned"),
    ("S6", "Verification and Recovery", "Evidence, idempotency and uncertainty", "Reliability", "Planned"),
    ("S7", "Privacy and Perception", "UIA, exclusions, labels and redaction", "Privacy", "Planned"),
    ("S8", "Tool Platform Core", "Catalog, retrieval, grants and runtime", "Tools", "Planned"),
    ("S9", "Initial MCP Pack", "Restricted browser/file/git/document/search tools", "Tools", "Planned"),
    ("S10", "Voice", "Wake, VAD, STT, TTS and interruption", "Interaction", "Planned"),
    ("S11", "3D Character", "Asset MVP, Godot overlay and animation states", "Character", "Planned"),
    ("S12", "Controlled Memory", "Admission, retrieval, provenance and deletion", "Memory", "Planned"),
    ("S13", "Integrated Workflows", "Research, documents and development reads", "Product", "Planned"),
    ("S14", "Supervised Desktop", "UIA interaction and workflow drafts", "Windows", "Planned"),
    ("S15", "Constrained Proactivity", "Triggers, budgets, reasons and quiet hours", "Agent", "Planned"),
    ("S16", "Hardening", "Security, privacy, reliability and performance", "Quality", "Planned"),
    ("S17", "Beta and Release", "Installer, pilot, documentation and gates", "Release", "Planned"),
]


STORIES: dict[str, list[tuple[str, str, str, str, int, str]]] = {
    "S0": [
        ("ARCH-001", "Approve architecture decision record set", "Architecture", "Lead Architect", 5, "Architecture v1 signed off"),
        ("SEC-001", "Create threat model and trust-boundary data-flow diagrams", "Security", "Security Engineer", 8, "Threats mapped to controls"),
        ("PLAT-001", "Create monorepo, CI quality gates and environments", "Platform", "Platform Engineer", 8, "Clean build/test pipeline"),
        ("UX-001", "Convert character references into production asset brief", "Character", "3D/UX Artist", 5, "Brief covers rig, LOD and accessories"),
        ("PM-001", "Baseline outcomes, scope, risks and sprint governance", "Program", "Product Owner", 3, "Backlog and gates approved"),
    ],
    "S1": [
        ("CON-001", "Define Task, ActionIntent and expected-effect schemas", "Contracts", "Platform Engineer", 8, "Schemas validated with examples"),
        ("CON-002", "Define policy decision, approval and capability grant schemas", "Contracts", "Security Engineer", 8, "Signature fields and expiry specified"),
        ("CON-003", "Define normalized result, evidence and audit schemas", "Contracts", "Reliability Engineer", 5, "Versioned compatibility tests pass"),
        ("IPC-001", "Prototype ACL-protected named-pipe service identity", "Platform", "Windows Engineer", 8, "Unauthorized clients rejected"),
    ],
    "S2": [
        ("POL-001", "Deploy local OPA service and signed policy bundles", "Security", "Security Engineer", 8, "Bundle signature/version enforced"),
        ("POL-002", "Implement R0–R4 deterministic risk classifier", "Security", "Security Engineer", 8, "Risk matrix tests pass"),
        ("POL-003", "Implement immutable root restrictions", "Security", "Windows Engineer", 8, "Conversation cannot modify restrictions"),
        ("POL-004", "Build policy decision test harness", "Quality", "QA/Security Engineer", 5, "Allow/deny/ask matrix automated"),
    ],
    "S3": [
        ("APR-001", "Build technically separate trusted approval UI", "Security UX", "Windows Engineer", 13, "Exact preview and expiry work"),
        ("SAFE-001", "Implement global emergency stop and tray pause", "Safety", "Windows Engineer", 8, "Actuation revokes within objective"),
        ("AUD-001", "Implement append-only hash-chained audit writer", "Audit", "Platform Engineer", 8, "Tamper checks and recovery pass"),
        ("OTEL-001", "Deploy OTel Collector and baseline trace correlation", "Observability", "SRE", 8, "Trace/task IDs visible end-to-end"),
    ],
    "S4": [
        ("AGT-001", "Implement LangGraph task state and deterministic gates", "Agent", "AI Engineer", 13, "Graph pauses/resumes at approval"),
        ("AGT-002", "Add durable checkpoints and idempotency references", "Reliability", "AI Engineer", 8, "Crash test does not duplicate work"),
        ("LLM-001", "Implement provider-neutral endpoint profiles", "LLM", "AI Engineer", 8, "Provider swap requires configuration only"),
        ("LLM-002", "Enforce structured outputs, budgets and circuit breakers", "LLM", "Platform Engineer", 8, "Malformed/budget tests stop safely"),
    ],
    "S5": [
        ("WIN-001", "Create signed standard-user C# Windows broker", "Windows", "Windows Engineer", 13, "Only declared capabilities exposed"),
        ("WIN-002", "Implement allowlisted application launch/focus", "Windows", "Windows Engineer", 8, "Publisher/path verified"),
        ("WIN-003", "Implement safe window, volume and media operations", "Windows", "Windows Engineer", 8, "State verified after operations"),
        ("WIN-004", "Implement single desktop lease and human takeover", "Safety", "Windows Engineer", 8, "Mouse/keyboard activity revokes lease"),
    ],
    "S6": [
        ("VER-001", "Build independent verifier service and predicate API", "Reliability", "Reliability Engineer", 13, "Three-state outcomes supported"),
        ("VER-002", "Implement process/window/file verification adapters", "Reliability", "Windows Engineer", 8, "Evidence independent of executor"),
        ("REL-001", "Implement idempotency registry and bounded retries", "Reliability", "Platform Engineer", 8, "Replay suite has zero duplicate effects"),
        ("REL-002", "Implement compensation and UNCERTAIN workflow", "Reliability", "AI Engineer", 5, "Non-idempotent uncertainty never retries"),
    ],
    "S7": [
        ("PRV-001", "Implement source-based privacy classification", "Privacy", "Privacy Engineer", 8, "Source policy overrides detector"),
        ("PRV-002", "Implement app/site/folder/region exclusions", "Privacy", "Windows Engineer", 13, "Excluded context never captured"),
        ("PRV-003", "Integrate local redaction and Presidio patterns", "Privacy", "Privacy Engineer", 8, "Release-view tests pass"),
        ("PER-001", "Implement metadata and UIA perception ladder", "Perception", "Windows Engineer", 13, "Screenshots used only when required"),
        ("PRV-004", "Implement private-mode indicators and short-lived buffers", "Privacy UX", "Interaction Engineer", 5, "State is always visible"),
    ],
    "S8": [
        ("TOOL-001", "Implement trusted catalog and signed tool contracts", "Tools", "Platform Engineer", 13, "Contract drift quarantines tool"),
        ("TOOL-002", "Implement hybrid retrieval and policy pre-filter", "Tools", "AI Engineer", 8, "Top-k evaluation meets threshold"),
        ("TOOL-003", "Implement capability validation and secret brokering", "Tools", "Security Engineer", 13, "Secrets absent from prompts/logs"),
        ("TOOL-004", "Implement result normalizer and runtime supervisor", "Tools", "Platform Engineer", 13, "Timeout/cancel/output limits pass"),
        ("TOOL-005", "Prototype ToolHive isolation on target Windows setup", "Tools", "SRE", 8, "Mount and egress tests pass"),
    ],
    "S9": [
        ("MCP-001", "Onboard Playwright MCP in isolated profile", "Tools", "Tool Engineer", 8, "Domain/download restrictions pass"),
        ("MCP-002", "Wrap Filesystem and Git MCP read-only", "Tools", "Tool Engineer", 13, "Root/junction/write tests pass"),
        ("MCP-003", "Onboard MarkItDown with sandboxed local parsing", "Tools", "Tool Engineer", 8, "Malicious/large documents bounded"),
        ("MCP-004", "Onboard Brave Search and Time MCP", "Tools", "Tool Engineer", 5, "Queries redacted; output tainted"),
        ("MCP-005", "Integrate MCP Inspector and scanning pipeline", "Security", "Security Engineer", 8, "Promotion requires scan record"),
    ],
    "S10": [
        ("VOX-001", "Select and integrate wake word, VAD and streaming STT", "Voice", "Interaction Engineer", 13, "Latency/false-wake baseline met"),
        ("VOX-002", "Integrate streaming TTS and lip-sync events", "Voice", "Interaction Engineer", 8, "First audio latency measured"),
        ("VOX-003", "Implement echo cancellation and barge-in", "Voice", "Interaction Engineer", 13, "User interruption works reliably"),
        ("VOX-004", "Add push-to-talk, sleep and privacy controls", "Voice", "UX Engineer", 5, "Controls accessible and audited"),
    ],
    "S11": [
        ("CHR-001", "Create rigged 3D character MVP from references", "Character", "3D Artist", 13, "Recognizable front/side/back asset"),
        ("CHR-002", "Build Godot transparent click-through overlay", "Character", "Godot Engineer", 13, "DPI/multi-monitor tests pass"),
        ("CHR-003", "Implement semantic animation state machine", "Character", "Godot Engineer", 8, "All Jarvis states visible"),
        ("CHR-004", "Add locomotion, facial and accessory animation", "Character", "3D/Animation Artist", 13, "Transitions stable at taskbar scale"),
    ],
    "S12": [
        ("MEM-001", "Implement memory classes and provenance schema", "Memory", "Data Engineer", 8, "Every item has source/labels/expiry"),
        ("MEM-002", "Implement admission, contradiction and dedupe logic", "Memory", "AI Engineer", 13, "Poisoning suite blocks instructions"),
        ("MEM-003", "Implement hybrid retrieval with permission filter", "Memory", "AI Engineer", 8, "Forbidden items never retrieve"),
        ("MEM-004", "Build inspect/edit/delete memory dashboard", "Memory UX", "Frontend Engineer", 13, "Deletion propagates to vectors/cache"),
    ],
    "S13": [
        ("WF-001", "Ship cited public research workflow", "Product", "AI/Tool Engineer", 8, "Claims preserve provenance"),
        ("WF-002", "Ship local document understanding workflow", "Product", "AI/Tool Engineer", 8, "Private docs stay within policy"),
        ("WF-003", "Ship read-only repository analysis workflow", "Product", "AI/Tool Engineer", 8, "No mutation capability available"),
        ("WF-004", "Build tool composition and parallel-read scheduler", "Tools", "Platform Engineer", 13, "DAG conflicts serialize correctly"),
    ],
    "S14": [
        ("UIA-001", "Implement UIA candidate retrieval and confidence scoring", "Windows", "Windows Engineer", 13, "Ambiguity causes stop/ask"),
        ("UIA-002", "Implement fresh-target check and semantic invocation", "Windows", "Windows Engineer", 13, "Stale target test cannot execute"),
        ("WF-005", "Implement shadow-mode workflow demonstration capture", "Learning", "AI Engineer", 8, "Draft skills cannot self-promote"),
        ("UX-002", "Build supervised execution timeline", "Product UX", "Frontend Engineer", 8, "User sees each pending/result step"),
    ],
    "S15": [
        ("PRO-001", "Implement deterministic trigger service", "Proactivity", "Platform Engineer", 8, "Only registered triggers fire"),
        ("PRO-002", "Implement relevance, quiet-hours and cooldown engine", "Proactivity", "AI Engineer", 8, "Frequency budgets enforced"),
        ("PRO-003", "Add visible reason and per-rule controls", "Proactivity UX", "Frontend Engineer", 5, "Every interruption is explainable"),
        ("PRO-004", "Integrate initial calendar/build/battery triggers", "Proactivity", "Tool Engineer", 8, "No consequential bypass"),
    ],
    "S16": [
        ("RED-001", "Run prompt-injection and confused-deputy campaign", "Security", "Red Team", 13, "Critical scenarios blocked"),
        ("RED-002", "Run MCP supply-chain and sandbox escape tests", "Security", "Red Team", 13, "No host-boundary escape"),
        ("QA-001", "Run privacy leakage and memory poisoning suite", "Quality", "QA/Privacy Engineer", 13, "Release thresholds met"),
        ("PERF-001", "Optimize voice, graph, policy and character latency", "Performance", "Performance Engineer", 8, "Latency budgets met"),
        ("DR-001", "Test backup, restore, crash and update rollback", "Reliability", "SRE", 8, "Recovery runbook passes"),
    ],
    "S17": [
        ("REL-003", "Create signed installer and rollback-capable updater", "Release", "Release Engineer", 13, "Signature/update rollback verified"),
        ("OPS-001", "Finalize Grafana action-review and operations dashboards", "Operations", "SRE", 8, "User can trace complete action"),
        ("DOC-001", "Complete user, administrator and incident documentation", "Documentation", "Technical Writer", 8, "Docs pass operational walkthrough"),
        ("BETA-001", "Run controlled pilot and resolve release blockers", "Release", "Product/QA", 13, "Pilot acceptance gates pass"),
        ("GATE-001", "Conduct production readiness review", "Governance", "Architecture Board", 5, "Go/no-go decision recorded"),
    ],
}


def build_xlsx() -> None:
    sheets: list[Sheet] = []
    start = date(2026, 10, 12)

    road = Sheet("Executive Roadmap",
                 ["Sprint", "Theme", "Objective", "Workstream", "Start", "End", "Status", "Story Points", "Story Count", "Exit Gate"],
                 [10, 24, 46, 18, 13, 13, 13, 13, 12, 44])
    gates = {
        "S0": "Architecture, threat model and backlog approved",
        "S3": "No action can bypass policy, approval or audit",
        "S6": "Verified/failed/uncertain behavior proven",
        "S9": "Initial MCP pack isolated and contract-pinned",
        "S11": "Voice and character usable as one experience",
        "S14": "Supervised desktop actions stop safely on ambiguity",
        "S16": "Adversarial and privacy release thresholds met",
        "S17": "Production readiness review approves beta release",
    }
    for i, (sid, theme, obj, stream, status) in enumerate(SPRINTS):
        sd = start + timedelta(days=14 * i)
        ed = sd + timedelta(days=11)
        styles = [3, 3, 3, 3, 4, 4, 5, 10, 10, 3]
        road.add([sid, theme, obj, stream, excel_date(sd), excel_date(ed), status, 0, 0, gates.get(sid, "Integrated increment demonstrated")], styles)
        rr = i + 2
        road.formula(rr, 8, f"SUMIF('Sprint Backlog'!$C:$C,A{rr},'Sprint Backlog'!$H:$H)")
        road.formula(rr, 9, f"COUNTIF('Sprint Backlog'!$C:$C,A{rr})")
    sheets.append(road)

    backlog = Sheet("Sprint Backlog",
                    ["Story ID", "Story", "Sprint", "Sprint Theme", "Workstream", "Owner Role", "Priority", "Points", "Dependencies", "Acceptance Criterion", "Status"],
                    [13, 46, 10, 24, 18, 22, 11, 9, 24, 48, 13])
    prev = "None"
    for sid, theme, *_ in SPRINTS:
        for story_id, title, workstream, owner, points, acceptance in STORIES[sid]:
            backlog.add([story_id, title, sid, theme, workstream, owner, "Must", points, prev, acceptance, "Planned"],
                        [3, 3, 3, 3, 3, 3, 3, 10, 3, 3, 5])
        prev = sid
    sheets.append(backlog)

    work = Sheet("Architecture Workstreams",
                 ["Workstream", "Primary Deliverables", "Key Interfaces", "Primary Owner", "Quality Evidence", "Target Sprints"],
                 [22, 52, 42, 22, 46, 18])
    for row in [
        ["Experience/Character", "3D asset, Godot overlay, semantic animation and status UI", "Interaction events; trusted UI separation", "Godot + 3D Team", "DPI, multi-monitor, frame time and accessibility tests", "S0, S10–S11"],
        ["Interaction", "Wake/VAD/STT/TTS, barge-in and privacy controls", "Orchestrator and character cues", "Interaction Engineer", "False-wake, latency and interruption metrics", "S10–S11"],
        ["Agent Orchestration", "LangGraph graphs, planning, checkpoints and recovery", "LLM gateway, policy and tool platform", "AI Engineer", "Bounded loop and crash/replay tests", "S4 onward"],
        ["Policy/Guardrails", "OPA, PEP/PIP, risk, approvals and grants", "All effectful paths", "Security Engineer", "Policy matrix and adversarial suite", "S1–S3, S16"],
        ["Windows", "Signed brokers, UIA, process containment and leases", "Policy grants and verifier", "Windows Engineer", "Publisher/target/takeover tests", "S5–S7, S14"],
        ["Tool Platform", "Registry, retrieval, contracts, isolation and MCP portfolio", "LangGraph, OPA and verifier", "Platform/Tool Engineer", "Contract drift and sandbox tests", "S8–S9, S13"],
        ["Privacy", "Exclusions, labels, redaction and release policy", "Sensors, LLM, memory and telemetry", "Privacy Engineer", "Leakage and excluded-app tests", "S7, S12, S16"],
        ["Verification", "Predicates, evidence, idempotency and uncertainty", "Every effectful capability", "Reliability Engineer", "No duplicate effects; evidence coverage", "S6 onward"],
        ["Memory", "Classes, admission, retrieval, provenance and deletion", "Orchestrator and privacy", "Data/AI Engineer", "Poisoning and deletion tests", "S12"],
        ["Observability/Audit", "OTel stack, action review and hash-chained journal", "All components", "SRE", "Trace completeness and tamper checks", "S3 onward"],
    ]:
        work.add(row)
    sheets.append(work)

    risks = Sheet("Risk Register",
                  ["Risk ID", "Risk", "Probability", "Impact", "Rating", "Mitigation", "Trigger/Indicator", "Owner", "Review Sprint", "Status"],
                  [11, 43, 13, 12, 11, 54, 39, 21, 15, 13])
    risk_rows = [
        ["R-01", "Indirect prompt injection causes tool misuse", "High", "Critical", "Critical", "Data/instruction separation, taint, OPA, destination checks and adversarial tests", "Observed content attempts to alter goal/authority", "Security Engineer", "Every sprint", "Open"],
        ["R-02", "MCP supply-chain compromise", "Medium", "Critical", "High", "Pin digests, SBOM/scan, isolation, egress/mount controls and quarantine", "Schema/digest/dependency changes", "Tool Platform Lead", "S8–S16", "Open"],
        ["R-03", "Private context reaches remote endpoint or telemetry", "Medium", "Critical", "High", "Local source policy, release views, secret tests and telemetry allowlists", "Secret canary appears outside privacy boundary", "Privacy Engineer", "S7–S16", "Open"],
        ["R-04", "UI automation targets wrong window or element", "High", "High", "High", "Publisher identity, fresh UIA snapshot, confidence margin and verification", "Focus/layout/DPI change between plan and action", "Windows Engineer", "S5–S16", "Open"],
        ["R-05", "Retry duplicates external effect", "Medium", "Critical", "High", "Idempotency registry, prepare/commit and stop on uncertainty", "Timeout after effect with missing response", "Reliability Engineer", "S6 onward", "Open"],
        ["R-06", "User mistakes character prompt for trusted approval", "Medium", "High", "High", "Separate signed native approval UI and consistent trusted visual language", "Approval shown inside avatar/website", "Security UX", "S3 onward", "Open"],
        ["R-07", "Character asset/overlay misses performance target", "Medium", "Medium", "Medium", "LOD, bounded physics, early Godot spike and frame-time budget", "High GPU/CPU or input interference", "Godot Lead", "S0, S11", "Open"],
        ["R-08", "Voice latency or false wakes harm trust", "Medium", "Medium", "Medium", "Local VAD/wake, model benchmarks, push-to-talk and latency telemetry", "False wake/response latency exceeds threshold", "Interaction Lead", "S10", "Open"],
        ["R-09", "Memory stores false or poisoned instructions", "Medium", "High", "High", "Quarantine, provenance, contradiction checks and no executable remembered text", "Untrusted claim retrieved as workflow", "Memory Lead", "S12–S16", "Open"],
        ["R-10", "Tool breadth creates unreliable selection", "High", "Medium", "High", "Progressive retrieval, initial 10–15 tools and selection evaluation", "Incorrect-tool/policy-denial rate rises", "AI/Tool Lead", "S8 onward", "Open"],
        ["R-11", "Target hardware cannot run full local stack", "Medium", "Medium", "Medium", "Baseline target hardware; configurable services; performance spike", "Sustained resource budget breach", "SRE", "S0, S10–S16", "Open"],
        ["R-12", "Audit/trace storage leaks content or grows unbounded", "Medium", "High", "High", "Field allowlists, retention tiers, quotas, encryption and review", "Unexpected content/cardinality/storage growth", "SRE/Privacy", "S3 onward", "Open"],
    ]
    for row in risk_rows:
        styles = [3] * 10
        if row[4] in ("Critical", "High"):
            styles[4] = 8
        risks.add(row, styles)
    sheets.append(risks)

    gates_sheet = Sheet("Acceptance Gates",
                        ["Gate", "Target Sprint", "Required Evidence", "Pass Condition", "Owner", "Status"],
                        [20, 14, 58, 58, 23, 13])
    gate_rows = [
        ["G0 Architecture", "S0", "ADRs, scope, threat model, data flow and backlog", "Architecture board approves baseline", "Lead Architect", "Planned"],
        ["G1 Control Plane", "S3", "Policy tests, approval signatures, emergency stop and audit chain", "No tested effect path bypasses controls", "Security Lead", "Planned"],
        ["G2 Safe Actuation", "S6", "Broker/lease, idempotency and independent verification suite", "Zero duplicate effects; uncertainty stops", "Reliability Lead", "Planned"],
        ["G3 Privacy", "S7", "Excluded-app, release-view, private-mode and telemetry leak tests", "Prohibited data does not cross boundary", "Privacy Lead", "Planned"],
        ["G4 Tool Platform", "S9", "Pinned contracts, isolation, egress/mount and drift tests", "All production tools pass onboarding", "Tool Platform Lead", "Planned"],
        ["G5 Experience", "S11", "Voice latency, barge-in, avatar state and multi-monitor tests", "Integrated experience meets usability baseline", "Experience Lead", "Planned"],
        ["G6 Memory", "S12", "Admission, provenance, poisoning and deletion evidence", "No prohibited/executable poisoned memory", "Memory Lead", "Planned"],
        ["G7 Supervised Agent", "S14", "UI ambiguity, takeover, workflow draft and end-to-end tests", "Supervised actions remain bounded and explainable", "Product/Safety", "Planned"],
        ["G8 Security Hardening", "S16", "Red-team, privacy, DR and performance reports", "No critical finding; thresholds achieved", "Security/QA", "Planned"],
        ["G9 Production Readiness", "S17", "Pilot results, signed installer, runbooks and dashboards", "Go decision recorded by review board", "Architecture Board", "Planned"],
    ]
    for row in gate_rows:
        gates_sheet.add(row, [3, 3, 3, 3, 3, 5])
    sheets.append(gates_sheet)

    raci = Sheet("RACI",
                 ["Deliverable", "Accountable", "Responsible", "Consulted", "Informed"],
                 [38, 25, 34, 42, 35])
    for row in [
        ["Architecture baseline", "Lead Architect", "Architecture Team", "Security, Product, Windows, AI", "All workstreams"],
        ["Policy and immutable restrictions", "Security Lead", "Security + Windows Engineers", "Privacy, Legal/Product", "All capability owners"],
        ["Trusted approval experience", "Security Lead", "Windows + UX Engineers", "Product, Accessibility", "Users/pilot"],
        ["LangGraph and model gateway", "AI Lead", "AI + Platform Engineers", "Security, Privacy, SRE", "Product"],
        ["Windows capability broker", "Windows Lead", "Windows Engineers", "Security, Reliability", "AI/Tool teams"],
        ["Tool Capability Platform", "Platform Lead", "Tool + Platform Engineers", "Security, AI, SRE", "Capability owners"],
        ["Privacy firewall", "Privacy Lead", "Privacy + Windows Engineers", "Security, Product", "All data processors"],
        ["Character and voice", "Experience Lead", "Godot/3D + Interaction Team", "Product, Accessibility, Performance", "Users/pilot"],
        ["Verification and audit", "Reliability Lead", "Reliability + SRE", "Security, Tool, Windows", "Architecture Board"],
        ["Production release", "Product Owner", "Release + QA + SRE", "All leads", "Stakeholders/users"],
    ]:
        raci.add(row)
    sheets.append(raci)

    dod = Sheet("Definition of Done",
                ["Category", "Required Check", "Evidence", "Applies To"],
                [22, 62, 45, 25])
    for row in [
        ["Code", "Reviewed, formatted, static checks clean and maintainability accepted", "CI report and review", "All engineering stories"],
        ["Contracts", "Versioned schema and compatibility tests updated", "Contract test report", "APIs/events/tools"],
        ["Security", "Threat impact reviewed; least privilege and denial paths tested", "Threat note and security tests", "Capabilities/data flows"],
        ["Privacy", "Classification, release, retention and deletion behavior tested", "Privacy test evidence", "Personal/sensitive data"],
        ["Policy", "Allow/deny/ask and obligations covered", "OPA test matrix", "Effectful actions"],
        ["Reliability", "Timeout, cancellation, retry, crash and uncertainty paths tested", "Failure-injection report", "Runtime components"],
        ["Verification", "Independent postcondition predicates implemented", "Evidence fixtures", "Effectful capabilities"],
        ["Observability", "Trace/metric/log fields added without sensitive content", "OTel test/dashboard", "Services/workflows"],
        ["Audit", "Security-relevant decisions/effects produce chained events", "Audit verification", "Policies/actions"],
        ["UX", "States, errors, approval and accessibility are understandable", "Usability/accessibility review", "User-facing stories"],
        ["Documentation", "ADR/runbook/user docs updated", "Published documents", "Behavioral/operational change"],
        ["Demo", "Acceptance criterion demonstrated in clean environment", "Recorded sprint evidence", "All stories"],
    ]:
        dod.add(row)
    sheets.append(dod)

    # Package workbook.
    wb = ET.Element(qn(X, "workbook"))
    ET.SubElement(wb, qn(X, "workbookPr"), {"date1904": "0"})
    wbviews = ET.SubElement(wb, qn(X, "bookViews")); ET.SubElement(wbviews, qn(X, "workbookView"), {"activeTab": "0"})
    ss = ET.SubElement(wb, qn(X, "sheets"))
    for i, sheet in enumerate(sheets, 1):
        ET.SubElement(ss, qn(X, "sheet"), {"name": sheet.name, "sheetId": str(i), qn(XR, "id"): f"rId{i}"})
    ET.SubElement(wb, qn(X, "calcPr"), {"calcId": "191029", "fullCalcOnLoad": "1", "forceFullCalc": "1", "calcMode": "auto"})

    wb_rels = ET.Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    for i in range(1, len(sheets) + 1):
        ET.SubElement(wb_rels, "Relationship", {"Id": f"rId{i}", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet", "Target": f"worksheets/sheet{i}.xml"})
    ET.SubElement(wb_rels, "Relationship", {"Id": f"rId{len(sheets)+1}", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "Target": "styles.xml"})

    root_rels = ET.Element("Relationships", xmlns="http://schemas.openxmlformats.org/package/2006/relationships")
    ET.SubElement(root_rels, "Relationship", {"Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "Target": "xl/workbook.xml"})
    ET.SubElement(root_rels, "Relationship", {"Id": "rId2", "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "Target": "docProps/core.xml"})
    ET.SubElement(root_rels, "Relationship", {"Id": "rId3", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties", "Target": "docProps/app.xml"})

    ct = ET.Element("Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types")
    ET.SubElement(ct, "Default", {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
    ET.SubElement(ct, "Default", {"Extension": "xml", "ContentType": "application/xml"})
    ET.SubElement(ct, "Override", {"PartName": "/xl/workbook.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"})
    ET.SubElement(ct, "Override", {"PartName": "/xl/styles.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"})
    for i in range(1, len(sheets) + 1):
        ET.SubElement(ct, "Override", {"PartName": f"/xl/worksheets/sheet{i}.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"})
    ET.SubElement(ct, "Override", {"PartName": "/docProps/core.xml", "ContentType": "application/vnd.openxmlformats-package.core-properties+xml"})
    ET.SubElement(ct, "Override", {"PartName": "/docProps/app.xml", "ContentType": "application/vnd.openxmlformats-officedocument.extended-properties+xml"})

    core = ET.Element(qn(CP, "coreProperties"))
    ET.SubElement(core, qn(DC, "title")).text = "Jarvis Implementation Sprint Plan"
    ET.SubElement(core, qn(DC, "creator")).text = "Jarvis Project"
    created = ET.SubElement(core, qn(DCTERMS, "created"), {qn(XSI, "type"): "dcterms:W3CDTF"}); created.text = "2026-10-08T00:00:00Z"
    app = ET.Element("Properties", xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
                     attrib={"xmlns:vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"})
    ET.SubElement(app, "Application").text = "Jarvis Sprint Generator"
    ET.SubElement(app, "Company").text = "Jarvis Project"

    with zipfile.ZipFile(XLSX_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", xml_bytes(ct))
        z.writestr("_rels/.rels", xml_bytes(root_rels))
        z.writestr("xl/workbook.xml", xml_bytes(wb))
        z.writestr("xl/_rels/workbook.xml.rels", xml_bytes(wb_rels))
        z.writestr("xl/styles.xml", xlsx_styles())
        for i, sheet in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", sheet.xml())
        z.writestr("docProps/core.xml", xml_bytes(core))
        z.writestr("docProps/app.xml", xml_bytes(app))


def validate_package(path: Path, required: list[str]) -> dict[str, object]:
    with zipfile.ZipFile(path, "r") as z:
        bad = z.testzip()
        names = set(z.namelist())
        missing = [x for x in required if x not in names]
        xml_count = 0
        for name in names:
            if name.endswith((".xml", ".rels")):
                ET.fromstring(z.read(name))
                xml_count += 1
        broken_relationships: list[str] = []
        rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        for rel_name in [n for n in names if n.endswith(".rels")]:
            rel_root = ET.fromstring(z.read(rel_name))
            if rel_name == "_rels/.rels":
                base = ""
            else:
                prefix, filename = rel_name.split("/_rels/", 1)
                source_name = filename[:-5]  # remove .rels
                base = posixpath.dirname(posixpath.join(prefix, source_name))
            for rel in rel_root.findall(f"{{{rel_ns}}}Relationship"):
                if rel.attrib.get("TargetMode") == "External":
                    continue
                target = posixpath.normpath(posixpath.join(base, rel.attrib["Target"]))
                if target not in names:
                    broken_relationships.append(f"{rel_name} -> {target}")
    if bad or missing or broken_relationships:
        raise RuntimeError(
            f"Invalid package {path}: bad={bad}, missing={missing}, broken_relationships={broken_relationships}")
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "parts": len(names),
        "xml_parts_validated": xml_count,
    }


def main() -> None:
    build_docx()
    build_xlsx()
    report = {
        "generated_at": "2026-10-12",
        "architecture_version": "1.7",
        "docx": validate_package(DOCX_PATH, ["word/document.xml", "word/styles.xml", "word/_rels/document.xml.rels"]),
        "xlsx": validate_package(XLSX_PATH, ["xl/workbook.xml", "xl/styles.xml", "xl/worksheets/sheet1.xml"]),
        "sprints": len(SPRINTS),
        "stories": sum(len(v) for v in STORIES.values()),
    }
    MANIFEST_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
