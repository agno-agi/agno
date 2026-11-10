from pathlib import Path

repo_root = Path(__file__).resolve().parents[3]
testing_resources_path = repo_root / "cookbook/07_knowledge/testing_resources"


def get_test_resource_path(filename: str) -> str:
    return str(testing_resources_path / filename)


pdf_path = get_test_resource_path("cv_1.pdf")
docx_path = get_test_resource_path("project_proposal.docx")
md_path = get_test_resource_path("coffee.md")
html_path = get_test_resource_path("company_info.html")
xml_path = get_test_resource_path("patent_sample.xml")
xlsx_path = get_test_resource_path("sample_products.xlsx")
pptx_path = get_test_resource_path("ai_presentation.pptx")
image_path = get_test_resource_path("restaurant_invoice.png")
audio_video_path = get_test_resource_path("agno_description.mp4")
