#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RV25j OCR Pipeline (Class Based)
Author: Improved for modular maintainability
"""

import argparse
import re
from pathlib import Path
from io import StringIO

import pandas as pd
from bs4 import BeautifulSoup
from paddleocr import PPStructureV3
import matplotlib.pyplot as plt

# ---- TOML reader (Python 3.11+ or older with tomli) -----------------
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # older Python
    import tomli as tomllib  # type: ignore


class RV25jProcessor:
    COLUMN_SPEC = "MARKER,,NORTHING,EASTING".split(",")

    def __init__(self, root_folder: str, skip_ocr: bool = False):
        self.root = Path(root_folder)
        self.skip_ocr = skip_ocr
        self.pipeline = None

        if not self.root.is_dir():
            raise ValueError(f"[ERROR] Folder not found: {self.root}")

        if not skip_ocr:
            print("[INFO] Init PaddleOCR Thai PP-StructureV3...")
            self.pipeline = PPStructureV3(
                lang="th",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                use_table_recognition=True,
            )

    # -----------------------------------------------------------
    def get_prefix(self, image_path: Path) -> str:
        stem = image_path.stem
        return stem[:-len("_table")] if stem.endswith("_table") else stem

    # -----------------------------------------------------------
    def parse_markdown_table(self, md_path: Path) -> pd.DataFrame:
        html = md_path.read_text(encoding="utf-8", errors="ignore").strip()
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")

        if not table:
            print(f"[WARN] No <table> in {md_path}")
            return pd.DataFrame(columns=[c for c in self.COLUMN_SPEC if c])

        try:
            df_raw = pd.read_html(StringIO(str(table)))[0].reset_index(drop=True)
        except Exception as e:
            print(f"[WARN] pandas.read_html failed {md_path}: {e}")
            return pd.DataFrame(columns=[c for c in self.COLUMN_SPEC if c])

        df_raw = df_raw.map(
            lambda x: "" if pd.isna(x) else str(x).replace("\xa0", " ").strip()
        )

        out_cols = [c for c in self.COLUMN_SPEC if c]
        rows = []

        for _, row in df_raw.iterrows():
            rec = {}
            for idx, colname in enumerate(self.COLUMN_SPEC):
                if not colname:
                    continue

                raw = row.iloc[idx].strip() if idx < len(df_raw.columns) else ""
                val = (
                    raw.replace("O", "0")
                    .replace("o", "0")
                    .replace("I", "1")
                    .replace("i", "1")
                    .replace("l", "1")
                    .replace("L", "1")
                )

                if colname in ("NORTHING", "EASTING"):
                    cleaned = re.sub(r"[^0-9.]", "", val)
                    if cleaned.count(".") > 1:
                        first, *rest = cleaned.split(".")
                        cleaned = first + "." + "".join(rest)
                    try:
                        val = f"{float(cleaned):.3f}"
                    except Exception:
                        val = ""
                rec[colname] = val

            if any(rec.values()):
                rows.append(rec)

        return pd.DataFrame(rows, columns=out_cols)

    # -----------------------------------------------------------
    def run_ocr(self, image_path: Path) -> pd.DataFrame:
        prefix = self.get_prefix(image_path)
        out_img_dir = image_path.parent / "imgs"
        out_img_dir.mkdir(exist_ok=True)

        print(f"\n[INFO] OCR: {image_path}")
        outputs = self.pipeline.predict(str(image_path))

        dfs = []
        for i, res in enumerate(outputs):
            md_file = image_path.parent / f"{prefix}_tbl{i:02d}.md"
            res.save_to_markdown(save_path=str(md_file))
            res.save_to_img(save_path=str(out_img_dir))

            df = self.parse_markdown_table(md_file)
            if not df.empty:
                dfs.append(df)

        return (
            pd.concat(dfs, ignore_index=True)
            if dfs
            else pd.DataFrame(columns=self.COLUMN_SPEC)
        )

    # -----------------------------------------------------------
    def parse_existing_md(self, image_path: Path) -> pd.DataFrame:
        prefix = self.get_prefix(image_path)
        md_files = sorted(image_path.parent.glob(f"{prefix}_tbl*.md"))

        if not md_files:
            print(f"[WARN] No MD found: {image_path}")
            return pd.DataFrame(columns=self.COLUMN_SPEC)

        dfs = [self.parse_markdown_table(md) for md in md_files]
        dfs = [df for df in dfs if not df.empty]
        return (
            pd.concat(dfs, ignore_index=True)
            if dfs
            else pd.DataFrame(columns=self.COLUMN_SPEC)
        )

    # -----------------------------------------------------------
    def _toml_escape(self, s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    def write_toml(self, image_path: Path, df: pd.DataFrame):
        """
        Build <prefix>_MAPL1.toml from OCR/MD DataFrame and
        return vertices list used for plotting.
        """
        prefix = self.get_prefix(image_path)
        toml_path = image_path.with_name(f"{prefix}_MAPL1.toml")

        vertices = []
        for _, r in df.iterrows():
            try:
                n = float(r["NORTHING"])
                e = float(r["EASTING"])
                vertices.append({"marker": r["MARKER"], "north": n, "east": e})
            except Exception:
                continue

        if not vertices:
            print(f"[WARN] No numeric rows: {image_path}")
            return [], False

        polygon_closed = False
        if len(vertices) >= 2:
            f, l = vertices[0], vertices[-1]
            if (
                abs(f["north"] - l["north"]) < 1e-3
                and abs(f["east"] - l["east"]) < 1e-3
                and f["marker"] == l["marker"]
            ):
                polygon_closed = True
                vertices = vertices[:-1]

        rows = []
        for idx, v in enumerate(vertices, start=1):
            label = chr(64 + idx) if idx <= 26 else f"P{idx}"
            rows.append([idx, label, v["marker"], v["north"], v["east"]])

        lines = [
            "[Deed]",
            'crs = "32647"',
            'unit = "meter"',
            f"polygon_closed = {'true' if polygon_closed else 'false'}",
            "marker = [",
        ]
        for idx, label, name, n, e in rows:
            lines.append(
                f'  [{idx}, "{self._toml_escape(label)}", '
                f'"{self._toml_escape(name)}", {n:.3f}, {e:.3f}],'
            )
        lines.append("]")

        toml_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"[OK] TOML → {toml_path}")
        return vertices, polygon_closed

    # -----------------------------------------------------------
    def load_vertices_from_side_toml(self, image_path: Path):
        """
        If <prefix>_MAPL1x.toml exists, read its `marker = [...]` and convert
        to vertices list: [{"marker": name, "north": N, "east": E}, ...].
        """
        prefix = self.get_prefix(image_path)
        side_path = image_path.with_name(f"{prefix}_MAPL1x.toml")

        if not side_path.is_file():
            return None

        print(f"[INFO] Found side TOML: {side_path}")
        try:
            text = side_path.read_text(encoding="utf-8")
            data = tomllib.loads(text)
        except Exception as e:
            print(f"[WARN] Failed to read/parse {side_path}: {e}")
            return None

        # marker may be at top-level or under [Deed]
        tbl = data.get("Deed", data)
        markers = tbl.get("marker")
        if not markers:
            print(f"[WARN] No 'marker' array in {side_path}")
            return None

        vertices = []
        for row in markers:
            # Expected: [idx, "A", "s24", 711494.218, 810313.001]
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            _, _label, name, north, east = row[:5]
            try:
                n = float(north)
                e = float(east)
            except (TypeError, ValueError):
                continue
            vertices.append({"marker": str(name), "north": n, "east": e})

        if not vertices:
            print(f"[WARN] No numeric vertices in {side_path}")
            return None

        return vertices

    # -----------------------------------------------------------
    def plot_polygon(self, image_path: Path, vertices: list):
        if len(vertices) < 2:
            print("[WARN] Not enough vertices → no plot")
            return

        prefix = self.get_prefix(image_path)
        out_png = image_path.with_name(f"{prefix}_plot.png")

        xs = [v["east"] for v in vertices] + [vertices[0]["east"]]
        ys = [v["north"] for v in vertices] + [vertices[0]["north"]]

        plt.figure(figsize=(7, 7))
        ax = plt.gca()
        ax.plot(xs, ys, "-o")

        for v in vertices:
            ax.text(
                v["east"],
                v["north"],
                f" {v['marker']}",
                fontsize=9,
                ha="left",
                va="bottom",
            )

        ax.set_aspect("equal", "box")
        ax.grid(True, linestyle="--", linewidth=0.5)
        ax.set_xlabel("EASTING (m)")
        ax.set_ylabel("NORTHING (m)")
        ax.set_title(prefix)
        plt.tight_layout()
        plt.savefig(out_png, dpi=200)
        plt.close()
        print(f"[OK] Plot → {out_png}")

    # -----------------------------------------------------------
    def process(self):
        images = sorted(self.root.rglob("*_table.jpg"))
        if not images:
            raise SystemExit("[ERROR] No *_table.jpg found")

        print(f"[INFO] Found {len(images)} files")

        for img in images:
            print("\n" + "=" * 70)
            print(f"[PROCESS] {img}")

            # 1) OCR or existing MD → DataFrame
            df = self.parse_existing_md(img) if self.skip_ocr else self.run_ocr(img)

            vertices_from_ocr = []
            if df.empty:
                print("[WARN] Empty DF from OCR/MD")
            else:
                vertices_from_ocr, closed = self.write_toml(img, df)

            # 2) Try side TOML override
            side_vertices = self.load_vertices_from_side_toml(img)

            if side_vertices:
                prefix = self.get_prefix(img)
                print(
                    f"[WARN] Plotting polygon from {prefix}_MAPL1x.toml "
                    "(side file override)."
                )
                self.plot_polygon(img, side_vertices)
            elif vertices_from_ocr:
                self.plot_polygon(img, vertices_from_ocr)
            else:
                print("[WARN] No vertices available → no plot")

        print("\n[DONE] Processing complete.")


# ============================================================
# CLI Entry
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="RV25j OCR → TOML → Plot (OOP)")
    parser.add_argument("folder", help="Folder containing *_table.jpg")
    parser.add_argument("-s", "--skip-ocr", action="store_true")
    args = parser.parse_args()

    processor = RV25jProcessor(args.folder, args.skip_ocr)
    processor.process()


if __name__ == "__main__":
    main()
