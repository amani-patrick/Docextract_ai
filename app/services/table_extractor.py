"""
Table extraction from OCR text blocks.

Strategy:
1. Cluster text blocks by Y-position into rows (spatial grouping).
2. Cluster columns by X-position within rows.
3. Detect if a region is table-like (≥2 rows, ≥2 cols, consistent structure).
4. Identify headers from the first row.
5. Build structured rows × cols output.

Works without any ML model — pure geometry on the bounding boxes.
For production upgrades: swap in TableTransformer (Microsoft) for PDF parsing.
"""

import logging
from collections import defaultdict
from typing import Optional

from app.models.responses import TextBlock, ExtractedTable, TableCell

logger = logging.getLogger("docuextract.table")


def _cluster_by_y(blocks: list[TextBlock], tolerance: float = 12.0) -> list[list[TextBlock]]:
    """Group blocks into rows by their vertical center position."""
    if not blocks:
        return []

    # Sort by vertical center
    sorted_blocks = sorted(blocks, key=lambda b: (b.bbox.y1 + b.bbox.y2) / 2)

    rows: list[list[TextBlock]] = []
    current_row: list[TextBlock] = [sorted_blocks[0]]
    current_y = (sorted_blocks[0].bbox.y1 + sorted_blocks[0].bbox.y2) / 2

    for block in sorted_blocks[1:]:
        block_y = (block.bbox.y1 + block.bbox.y2) / 2
        if abs(block_y - current_y) <= tolerance:
            current_row.append(block)
        else:
            rows.append(sorted(current_row, key=lambda b: b.bbox.x1))
            current_row = [block]
            current_y = block_y

    if current_row:
        rows.append(sorted(current_row, key=lambda b: b.bbox.x1))

    return rows


def _cluster_columns(rows: list[list[TextBlock]], tolerance: float = 20.0) -> list[float]:
    """Identify column X-boundaries across all rows."""
    all_x_starts = []
    for row in rows:
        for block in row:
            all_x_starts.append(block.bbox.x1)

    if not all_x_starts:
        return []

    # Simple 1D clustering
    all_x_starts.sort()
    columns = [all_x_starts[0]]
    for x in all_x_starts[1:]:
        if x - columns[-1] > tolerance:
            columns.append(x)

    return columns


def _assign_to_col(block: TextBlock, col_starts: list[float]) -> int:
    """Assign a text block to the nearest column index."""
    block_x = block.bbox.x1
    dists = [abs(block_x - c) for c in col_starts]
    return dists.index(min(dists))


def _is_table_like(rows: list[list[TextBlock]], min_cols: int = 2, min_rows: int = 2) -> bool:
    """Heuristic: a region is table-like if most rows have ≥ min_cols blocks."""
    if len(rows) < min_rows:
        return False
    col_counts = [len(r) for r in rows]
    avg_cols = sum(col_counts) / len(col_counts)
    return avg_cols >= min_cols


def _avg_confidence(cells: list[TableCell]) -> float:
    confs = [c.confidence for c in cells]
    return round(sum(confs) / len(confs), 4) if confs else 0.0


def extract_tables(
    blocks: list[TextBlock],
    page: Optional[int] = None,
    row_tolerance: float = 12.0,
    col_tolerance: float = 20.0,
    min_table_rows: int = 2,
    min_table_cols: int = 2,
) -> list[ExtractedTable]:
    """
    Extract structured tables from OCR text blocks.
    Returns list of ExtractedTable objects.
    """

    # Filter to specific page if requested
    if page is not None:
        blocks = [b for b in blocks if b.bbox.page == page]

    # Group by page first, then detect tables per page
    pages: dict[int, list[TextBlock]] = defaultdict(list)
    for b in blocks:
        pages[b.bbox.page].append(b)

    all_tables: list[ExtractedTable] = []
    table_idx = 0

    for pg_num, pg_blocks in sorted(pages.items()):
        rows = _cluster_by_y(pg_blocks, tolerance=row_tolerance)

        if not _is_table_like(rows, min_table_cols, min_table_rows):
            logger.debug(f"Page {pg_num}: not table-like, skipping")
            continue

        col_starts = _cluster_columns(rows, tolerance=col_tolerance)
        if len(col_starts) < min_table_cols:
            continue

        # Build grid
        grid: list[list[str]] = []
        raw_cells: list[TableCell] = []

        for row_idx, row in enumerate(rows):
            grid_row = [""] * len(col_starts)
            for block in row:
                col_idx = _assign_to_col(block, col_starts)
                if col_idx < len(grid_row):
                    grid_row[col_idx] = (grid_row[col_idx] + " " + block.text).strip()
                    raw_cells.append(TableCell(
                        row=row_idx,
                        col=col_idx,
                        text=block.text,
                        confidence=block.confidence,
                    ))
            grid.append(grid_row)

        if not grid:
            continue

        # First row as headers
        headers = grid[0]
        data_rows = grid[1:]

        table = ExtractedTable(
            table_index=table_idx,
            page=pg_num,
            headers=headers,
            rows=data_rows,
            raw_cells=raw_cells,
            confidence=_avg_confidence(raw_cells),
        )
        all_tables.append(table)
        table_idx += 1
        logger.info(f"Page {pg_num}: extracted table with {len(headers)} cols × {len(data_rows)} rows")

    return all_tables
