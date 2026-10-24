"""Build REPORT.docx from REPORT.md: right-to-left Hebrew, with styled tables.

    python make_docx.py      (needs pandoc on PATH)
"""
from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC, OUT = ROOT / "REPORT.md", ROOT / "REPORT.docx"

TABLE_WIDTH = 9000  # twips (~15.9 cm), the text width of an A4/Letter page
HEADER_FILL, ZEBRA_FILL, TOTAL_FILL, BORDER = "1F4E79", "F2F6FA", "DCE6F1", "A6A6A6"


def table_props(n_cols: int) -> tuple[str, str]:
    first = TABLE_WIDTH // 2
    other = (TABLE_WIDTH - first) // (n_cols - 1)
    widths = [first] + [other] * (n_cols - 1)
    borders = "".join(f'<w:{s} w:val="single" w:sz="6" w:space="0" w:color="{BORDER}"/>'
                      for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    tbl_pr = ('<w:tblPr><w:tblStyle w:val="Table"/><w:bidiVisual/>'
              f'<w:tblW w:w="{TABLE_WIDTH}" w:type="dxa"/><w:jc w:val="left"/>'
              f'<w:tblBorders>{borders}</w:tblBorders><w:tblLayout w:type="fixed"/>'
              '<w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="140" w:type="dxa"/>'
              '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="140" w:type="dxa"/></w:tblCellMar>'
              '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
              '</w:tblPr>')
    grid = "<w:tblGrid>" + "".join(f'<w:gridCol w:w="{w}"/>' for w in widths) + "</w:tblGrid>"
    return tbl_pr + grid, widths


def style_cell(cell: str, width: int, col: int, kind: str, keep_next: bool) -> str:
    """kind: header | total | zebra | plain."""
    fill = {"header": HEADER_FILL, "total": TOTAL_FILL, "zebra": ZEBRA_FILL}.get(kind)
    tc_pr = f'<w:tcPr><w:tcW w:w="{width}" w:type="dxa"/><w:vAlign w:val="center"/>'
    if fill:
        tc_pr += f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>'
    tc_pr += "</w:tcPr>"
    cell = re.sub(r"<w:tcPr>.*?</w:tcPr>", "", cell)
    cell = cell.replace("<w:tc>", "<w:tc>" + tc_pr, 1)
    # in an RTL paragraph "right" is the start: labels on the right, numbers centered
    align = "right" if col == 0 else "center"
    cell = re.sub(r'<w:jc w:val="\w+" ?/>', f'<w:jc w:val="{align}"/>', cell)
    if "<w:jc " not in cell:
        cell = cell.replace("<w:p>", f'<w:p><w:pPr><w:bidi/><w:jc w:val="{align}"/></w:pPr>')
    if keep_next:  # keeps the whole table on one page
        cell = cell.replace("<w:bidi />", "<w:keepNext/><w:bidi />").replace("<w:bidi/>", "<w:keepNext/><w:bidi/>")
    run_extra = ""
    if kind == "header":
        run_extra = '<w:b/><w:bCs/><w:color w:val="FFFFFF"/>'
    elif kind == "total":
        run_extra = "<w:b/><w:bCs/>"
    if "לא הורץ" in cell:
        run_extra += '<w:i/><w:iCs/><w:color w:val="808080"/>'
    if run_extra:
        cell = re.sub(r"<w:rPr>", "<w:rPr>" + run_extra, cell)
        cell = re.sub(r"<w:r>(?!<w:rPr>)", "<w:r><w:rPr>" + run_extra + "</w:rPr>", cell)
    return cell


def style_table(tbl: str) -> str:
    rows = re.findall(r"<w:tr>.*?</w:tr>", tbl, flags=re.S)
    n_cols = len(re.findall(r"<w:tc>", rows[0]))
    props, widths = table_props(n_cols)
    out_rows = []
    for i, row in enumerate(rows):
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", row))
        kind = "header" if i == 0 else "total" if 'סה"כ' in text else "zebra" if i % 2 == 0 else "plain"
        cells = re.findall(r"<w:tc>.*?</w:tc>", row, flags=re.S)
        styled = "".join(style_cell(c, widths[j], j, kind, i < len(rows) - 1) for j, c in enumerate(cells))
        tr_pr = "<w:trPr><w:cantSplit/>" + ("<w:tblHeader/>" if kind == "header" else "") + "</w:trPr>"
        out_rows.append(f"<w:tr>{tr_pr}{styled}</w:tr>")
    return "<w:tbl>" + props + "".join(out_rows) + "</w:tbl>"


def main() -> None:
    # relative paths + cwd: pandoc 2.x mangles non-ASCII (Hebrew) absolute paths on Windows
    raw = ROOT / "_pandoc.docx"
    subprocess.run(["pandoc", SRC.name, "-f", "gfm", "-t", "docx", "-M", "dir=rtl", "-M", "lang=he-IL",
                    "-o", raw.name], check=True, cwd=ROOT)
    tmp = OUT.with_suffix(".tmp")
    with zipfile.ZipFile(raw) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = data.decode("utf-8")
                xml = re.sub(r"<w:tbl>.*?</w:tbl>", lambda m: style_table(m.group(0)), xml, flags=re.S)
                # keep the paragraph right before each table on the same page as the table
                xml = re.sub(r"(<w:p>(?:(?!<w:p>).)*?<w:bidi ?/>)((?:(?!<w:p>).)*?</w:p><w:tbl>)",
                             lambda m: m.group(1).replace("<w:bidi", "<w:keepNext/><w:bidi", 1) + m.group(2), xml, flags=re.S)
                data = xml.encode("utf-8")
            elif item.filename == "word/styles.xml":
                xml = data.decode("utf-8")
                xml = xml.replace('w:cstheme="minorBidi"', 'w:cs="Arial"').replace('w:bidi="ar-SA"', 'w:bidi="he-IL"')
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    raw.unlink()
    try:
        shutil.move(tmp, OUT)
    except PermissionError:
        raise SystemExit(f"{OUT.name} is open in Word: close it and run again ({tmp.name} has the new version)")
    print(f"wrote {OUT.name}")


if __name__ == "__main__":
    main()
