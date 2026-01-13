from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class InvestmentType(str, Enum):
    EQUITY = "equity"
    DEBT = "debt"
    HYBRID = "hybrid"
    VENTURE = "venture"
    GROWTH = "growth"
    BUYOUT = "buyout"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class InvestmentAnalysisRequest(BaseModel):
    companies: List[str] = Field(
        ..., min_length=1, max_length=3, description="List of 1-3 companies to analyze"
    )
    investment_type: InvestmentType = Field(
        ..., description="Type of investment being considered"
    )
    investment_amount: Optional[float] = Field(
        default=None, description="Investment amount in USD"
    )
    investment_horizon: Optional[str] = Field(
        default=None, description="Investment time horizon (e.g., '3-5 years')"
    )
    target_return: Optional[float] = Field(
        default=None, description="Target return percentage"
    )
    risk_tolerance: Optional[RiskLevel] = Field(
        default=None, description="Risk tolerance level"
    )
    sectors: List[str] = Field(
        default_factory=list, description="Target sectors for analysis"
    )
    analyses_requested: List[str] = Field(
        ..., min_length=1, description="List of analysis types to perform"
    )
    benchmark_indices: List[str] = Field(
        default_factory=list, description="Benchmark indices for comparison"
    )
    comparable_companies: List[str] = Field(
        default_factory=list, description="Comparable companies for analysis"
    )


class FinancialMetrics(BaseModel):
    revenue: Optional[float] = None
    revenue_growth: Optional[float] = None
    net_income: Optional[float] = None
    ebitda: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    pe_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    free_cash_flow: Optional[float] = None
    cash_per_share: Optional[float] = None
    market_cap: Optional[float] = None


class CompanyProfile(BaseModel):
    name: str
    ticker: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    headquarters: Optional[str] = None
    founded_year: Optional[int] = None
    employees: Optional[int] = None
    description: Optional[str] = None
    business_model: Optional[str] = None
    competitive_advantages: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    recent_developments: List[str] = Field(default_factory=list)


class ValuationAnalysis(BaseModel):
    company_name: str
    dcf_valuation: Optional[float] = None
    comparable_multiples: Dict[str, float] = Field(default_factory=dict)
    asset_based_valuation: Optional[float] = None
    sum_of_parts: Optional[float] = None
    current_price: Optional[float] = None
    target_price: Optional[float] = None
    upside_potential: Optional[float] = None
    valuation_summary: Optional[str] = None


class RiskAssessment(BaseModel):
    company_name: str
    financial_risk_score: Optional[int] = Field(default=None, ge=1, le=10)
    operational_risk_score: Optional[int] = Field(default=None, ge=1, le=10)
    market_risk_score: Optional[int] = Field(default=None, ge=1, le=10)
    regulatory_risk_score: Optional[int] = Field(default=None, ge=1, le=10)
    esg_risk_score: Optional[int] = Field(default=None, ge=1, le=10)
    overall_risk_score: Optional[int] = Field(default=None, ge=1, le=10)
    risk_factors: List[str] = Field(default_factory=list)
    risk_mitigation: List[str] = Field(default_factory=list)


class MarketAnalysis(BaseModel):
    sector: str
    market_size: Optional[float] = None
    growth_rate: Optional[float] = None
    market_trends: List[str] = Field(default_factory=list)
    competitive_landscape: Optional[str] = None
    barriers_to_entry: List[str] = Field(default_factory=list)
    growth_drivers: List[str] = Field(default_factory=list)
    headwinds: List[str] = Field(default_factory=list)


class InvestmentRecommendation(BaseModel):
    company_name: str
    recommendation: str = Field(
        ..., description="BUY, HOLD, SELL, or STRONG_BUY/STRONG_SELL"
    )
    target_price: Optional[float] = None
    price_target_timeframe: Optional[str] = None
    conviction_level: Optional[int] = Field(default=None, ge=1, le=10)
    key_catalysts: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)
    rationale: Optional[str] = None


class InvestmentAnalysisResponse(BaseModel):
    request: InvestmentAnalysisRequest
    company_profiles: List[CompanyProfile] = Field(default_factory=list)
    financial_analysis: Optional[str] = None
    valuation_analysis: List[ValuationAnalysis] = Field(default_factory=list)
    risk_assessment: List[RiskAssessment] = Field(default_factory=list)
    market_analysis: List[MarketAnalysis] = Field(default_factory=list)
    esg_analysis: Optional[str] = None
    technical_analysis: Optional[str] = None
    peer_comparison: Optional[str] = None
    investment_recommendations: List[InvestmentRecommendation] = Field(
        default_factory=list
    )
    portfolio_fit: Optional[str] = None
    executive_summary: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None
    analysis_timestamp: Optional[str] = None
