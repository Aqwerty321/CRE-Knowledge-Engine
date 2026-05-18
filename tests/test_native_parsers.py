from __future__ import annotations

from pathlib import Path

from app.extraction import parse_source_file


def test_pdf_fixture_extracts_page_chunk_text() -> None:
    parsed = parse_source_file(
        Path("sample-data/files/main-street-office-flyer.pdf"),
        source_type="pdf",
        mime_type="application/pdf",
    )

    assert "120 Main St" in parsed.raw_text
    assert parsed.chunks
    assert parsed.chunks[0].page_number == 1
    assert parsed.chunks[0].metadata["parser"] == "pdf"


def test_xlsx_fixture_extracts_sheet_and_row_chunks() -> None:
    parsed = parse_source_file(
        Path("sample-data/files/broker-availability-tracker.xlsx"),
        source_type="xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert "700 Logistics Pkwy" in parsed.raw_text
    assert any(chunk.metadata.get("sheet_name") == "Availability" for chunk in parsed.chunks)
    assert any(chunk.row_number == 2 for chunk in parsed.chunks)