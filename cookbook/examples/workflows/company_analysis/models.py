from typing import List, Optional

from pydantic import BaseModel, Field


class ProcurementAnalysisRequest(BaseModel):
    companies: List[str] = Field(
        ..., min_length=1, max_length=5, description="List of 1-5 companies to analyze"
    )
    category_name: str = Field(
        ..., min_length=1, description="Category name for analysis"
    )
    analyses_requested: List[str] = Field(
        ..., min_length=1, description="List of analysis types to perform"
    )
    buyer_org_url: Optional[str] = Field(
        default=None, description="Buyer organization URL for context"
    )
    annual_spend: Optional[float] = Field(
        default=None, description="Annual spend amount for context"
    )
    region: Optional[str] = Field(default=None, description="Regional context")
    incumbent_suppliers: List[str] = Field(
        default_factory=list, description="Current/incumbent suppliers"
    )


class ProcurementAnalysisResponse(BaseModel):
    request: ProcurementAnalysisRequest
    company_overview: Optional[str] = None
    switching_barriers_analysis: Optional[str] = None
    pestle_analysis: Optional[str] = None
    porter_analysis: Optional[str] = None
    kraljic_analysis: Optional[str] = None
    cost_drivers_analysis: Optional[str] = None
    alternative_suppliers_analysis: Optional[str] = None
    final_report: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None


class AnalysisConfig(BaseModel):
    analysis_type: str = Field(..., description="Type of analysis to perform")
    max_companies: int = Field(
        default=5, description="Maximum number of companies to analyze"
    )
    include_market_data: bool = Field(
        default=True, description="Whether to include market data in analysis"
    )
    include_financial_data: bool = Field(
        default=True, description="Whether to include financial data in analysis"
    )


class CompanyProfile(BaseModel):
    name: str = Field(..., description="Company name")
    legal_name: Optional[str] = Field(default=None, description="Full legal name")
    industry: Optional[str] = Field(default=None, description="Industry/sector")
    founded_year: Optional[int] = Field(default=None, description="Year founded")
    headquarters: Optional[str] = Field(
        default=None, description="Headquarters location"
    )
    annual_revenue: Optional[float] = Field(
        default=None, description="Annual revenue in USD"
    )
    employee_count: Optional[int] = Field(
        default=None, description="Number of employees"
    )
    market_cap: Optional[float] = Field(
        default=None, description="Market capitalization in USD"
    )
    website: Optional[str] = Field(default=None, description="Company website")
    description: Optional[str] = Field(default=None, description="Company description")


class SupplierProfile(BaseModel):
    name: str = Field(..., description="Supplier name")
    website: Optional[str] = Field(default=None, description="Supplier website")
    headquarters: Optional[str] = Field(
        default=None, description="Headquarters location"
    )
    geographic_coverage: List[str] = Field(
        default_factory=list, description="Geographic coverage areas"
    )
    technical_capabilities: List[str] = Field(
        default_factory=list, description="Technical capabilities"
    )
    certifications: List[str] = Field(
        default_factory=list, description="Quality certifications"
    )
    annual_revenue: Optional[float] = Field(
        default=None, description="Annual revenue in USD"
    )
    employee_count: Optional[int] = Field(
        default=None, description="Number of employees"
    )
    key_differentiators: List[str] = Field(
        default_factory=list, description="Key competitive advantages"
    )
    financial_stability_score: Optional[int] = Field(
        default=None, ge=1, le=10, description="Financial stability score (1-10)"
    )
    suitability_score: Optional[int] = Field(
        default=None,
        ge=1,
        le=10,
        description="Suitability score for requirements (1-10)",
    )


class AnalysisResult(BaseModel):
    analysis_type: str = Field(..., description="Type of analysis performed")
    company_name: str = Field(..., description="Company analyzed")
    category_name: str = Field(..., description="Category analyzed")
    score: Optional[int] = Field(
        default=None, ge=1, le=9, description="Overall score (1-9 scale)"
    )
    summary: Optional[str] = Field(default=None, description="Analysis summary")
    detailed_findings: Optional[str] = Field(
        default=None, description="Detailed analysis findings"
    )
    recommendations: List[str] = Field(
        default_factory=list, description="Key recommendations"
    )
    risk_factors: List[str] = Field(
        default_factory=list, description="Identified risk factors"
    )
    success: bool = Field(
        default=True, description="Whether analysis completed successfully"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if analysis failed"
    )
