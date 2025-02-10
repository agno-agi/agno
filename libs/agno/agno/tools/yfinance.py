import json

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import yfinance as yf
except ImportError:
    raise ImportError("`yfinance` not installed. Please install using `pip install yfinance`.")


class YFinanceTools(Toolkit):
    def __init__(
        self,
        stock_price: bool = True,
        company_info: bool = False,
        stock_fundamentals: bool = False,
        income_statements: bool = False,
        key_financial_ratios: bool = False,
        analyst_recommendations: bool = False,
        company_news: bool = False,
        technical_indicators: bool = False,
        historical_prices: bool = False,
        enable_all: bool = False,
    ):
        super().__init__(name="yfinance_tools")

        if stock_price or enable_all:
            self.register(self.get_current_stock_price)
        if company_info or enable_all:
            self.register(self.get_company_info)
        if stock_fundamentals or enable_all:
            self.register(self.get_stock_fundamentals)
        if income_statements or enable_all:
            self.register(self.get_income_statements)
        if key_financial_ratios or enable_all:
            self.register(self.get_key_financial_ratios)
        if analyst_recommendations or enable_all:
            self.register(self.get_analyst_recommendations)
        if company_news or enable_all:
            self.register(self.get_company_news)
        if technical_indicators or enable_all:
            self.register(self.get_technical_indicators)
        if historical_prices or enable_all:
            self.register(self.get_historical_stock_prices)

    def get_current_stock_price(self, symbol: str) -> str:
        """
        Use this function to get the current stock price for a given symbol.

        Args:
            symbol (str): The stock symbol.

        Returns:
            str: The current stock price or error message.
        """
        try:
            logger.debug(f"Fetching current price for {symbol}")
            stock = yf.Ticker(symbol)
            # Use "regularMarketPrice" for regular market hours, or "currentPrice" for pre/post market
            current_price = stock.info.get("regularMarketPrice", stock.info.get("currentPrice"))
            return f"{current_price:.4f}" if current_price else f"Could not fetch current price for {symbol}"
        except Exception as e:
            return f"Error fetching current price for {symbol}: {e}"

    def get_company_info(self, symbol: str) -> str:
        """Use this function to get company information and overview for a given stock symbol.

        Args:
            symbol (str): The stock symbol.

        Returns:
            str: JSON containing company profile and overview.
        """
        try:
            company_info_full = yf.Ticker(symbol).info
            if company_info_full is None:
                return f"Could not fetch company info for {symbol}"

            logger.debug(f"Fetching company info for {symbol}")

            company_info_cleaned = {
                "Name": company_info_full.get("shortName"),
                "Symbol": company_info_full.get("symbol"),
                "Current Stock Price": f"{company_info_full.get('regularMarketPrice', company_info_full.get('currentPrice'))} {company_info_full.get('currency', 'USD')}",
                "Market Cap": f"{company_info_full.get('marketCap', company_info_full.get('enterpriseValue'))} {company_info_full.get('currency', 'USD')}",
                "Sector": company_info_full.get("sector"),
                "Industry": company_info_full.get("industry"),
                "Address": company_info_full.get("address1"),
                "City": company_info_full.get("city"),
                "State": company_info_full.get("state"),
                "Zip": company_info_full.get("zip"),
                "Country": company_info_full.get("country"),
                "EPS": company_info_full.get("trailingEps"),
                "P/E Ratio": company_info_full.get("trailingPE"),
                "52 Week Low": company_info_full.get("fiftyTwoWeekLow"),
                "52 Week High": company_info_full.get("fiftyTwoWeekHigh"),
                "50 Day Average": company_info_full.get("fiftyDayAverage"),
                "200 Day Average": company_info_full.get("twoHundredDayAverage"),
                "Website": company_info_full.get("website"),
                "Summary": company_info_full.get("longBusinessSummary"),
                "Analyst Recommendation": company_info_full.get("recommendationKey"),
                "Number Of Analyst Opinions": company_info_full.get("numberOfAnalystOpinions"),
                "Employees": company_info_full.get("fullTimeEmployees"),
                "Total Cash": company_info_full.get("totalCash"),
                "Free Cash flow": company_info_full.get("freeCashflow"),
                "Operating Cash flow": company_info_full.get("operatingCashflow"),
                "EBITDA": company_info_full.get("ebitda"),
                "Revenue Growth": company_info_full.get("revenueGrowth"),
                "Gross Margins": company_info_full.get("grossMargins"),
                "Ebitda Margins": company_info_full.get("ebitdaMargins"),
            }
            return json.dumps(company_info_cleaned, indent=2)
        except Exception as e:
            return f"Error fetching company profile for {symbol}: {e}"

    def get_historical_stock_prices(self, symbol: str, period: str = "1mo", interval: str = "1d") -> str:
        """
        Use this function to get the historical stock price for a given symbol.

        Args:
            symbol (str): The stock symbol.
            period (str): The period for which to retrieve historical prices. Defaults to "1mo".
                        Valid periods: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max
            interval (str): The interval between data points. Defaults to "1d".
                        Valid intervals: 1d,5d,1wk,1mo,3mo

        Returns:
          str: The current stock price or error message.
        """
        try:
            logger.debug(f"Fetching historical prices for {symbol}")
            stock = yf.Ticker(symbol)
            historical_price = stock.history(period=period, interval=interval)
            return historical_price.to_json(orient="index")
        except Exception as e:
            return f"Error fetching historical prices for {symbol}: {e}"

    def get_stock_fundamentals(self, symbol: str) -> str:
        """Use this function to get fundamental data for a given stock symbol yfinance API.

        Args:
            symbol (str): The stock symbol.

        Returns:
            str: A JSON string containing fundamental data or an error message.
                Keys:
                    - 'symbol': The stock symbol.
                    - 'company_name': The long name of the company.
                    - 'sector': The sector to which the company belongs.
                    - 'industry': The industry to which the company belongs.
                    - 'market_cap': The market capitalization of the company.
                    - 'pe_ratio': The forward price-to-earnings ratio.
                    - 'pb_ratio': The price-to-book ratio.
                    - 'dividend_yield': The dividend yield.
                    - 'eps': The trailing earnings per share.
                    - 'beta': The beta value of the stock.
                    - '52_week_high': The 52-week high price of the stock.
                    - '52_week_low': The 52-week low price of the stock.
        """
        try:
            logger.debug(f"Fetching fundamentals for {symbol}")
            stock = yf.Ticker(symbol)
            info = stock.info
            fundamentals = {
                "symbol": symbol,
                "company_name": info.get("longName", ""),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "market_cap": info.get("marketCap", "N/A"),
                "pe_ratio": info.get("forwardPE", "N/A"),
                "pb_ratio": info.get("priceToBook", "N/A"),
                "dividend_yield": info.get("dividendYield", "N/A"),
                "eps": info.get("trailingEps", "N/A"),
                "beta": info.get("beta", "N/A"),
                "52_week_high": info.get("fiftyTwoWeekHigh", "N/A"),
                "52_week_low": info.get("fiftyTwoWeekLow", "N/A"),
            }
            return json.dumps(fundamentals, indent=2)
        except Exception as e:
            return f"Error getting fundamentals for {symbol}: {e}"

    def get_income_statements(self, symbol: str) -> str:
        """Use this function to get income statements for a given stock symbol.

        Args:
            symbol (str): The stock symbol.

        Returns:
            dict: JSON containing income statements or an empty dictionary.
        """
        try:
            logger.debug(f"Fetching income statements for {symbol}")
            stock = yf.Ticker(symbol)
            financials = stock.financials
            return financials.to_json(orient="index")
        except Exception as e:
            return f"Error fetching income statements for {symbol}: {e}"

    def get_key_financial_ratios(self, symbol: str) -> str:
        """Use this function to get key financial ratios for a given stock symbol.

        Args:
            symbol (str): The stock symbol.

        Returns:
            dict: JSON containing key financial ratios.
        """
        try:
            logger.debug(f"Fetching key financial ratios for {symbol}")
            stock = yf.Ticker(symbol)
            key_ratios = stock.info
            return json.dumps(key_ratios, indent=2)
        except Exception as e:
            return f"Error fetching key financial ratios for {symbol}: {e}"

    def get_analyst_recommendations(self, symbol: str) -> str:
        """Use this function to get analyst recommendations for a given stock symbol.

        Args:
            symbol (str): The stock symbol.

        Returns:
            str: JSON containing analyst recommendations.
        """
        try:
            logger.debug(f"Fetching analyst recommendations for {symbol}")
            stock = yf.Ticker(symbol)
            recommendations = stock.recommendations
            return recommendations.to_json(orient="index")
        except Exception as e:
            return f"Error fetching analyst recommendations for {symbol}: {e}"

    def get_company_news(self, symbol: str, num_stories: int = 3) -> str:
        """Use this function to get company news and press releases for a given stock symbol.

        Args:
            symbol (str): The stock symbol.
            num_stories (int): The number of news stories to return. Defaults to 3.

        Returns:
            str: JSON containing company news and press releases.
        """
        try:
            logger.debug(f"Fetching company news for {symbol}")
            news = yf.Ticker(symbol).news
            return json.dumps(news[:num_stories], indent=2)
        except Exception as e:
            return f"Error fetching company news for {symbol}: {e}"

    def get_technical_indicators(self, symbol: str, period: str = "3mo") -> str:
        """Use this function to get technical indicators for a given stock symbol.

        Args:
            symbol (str): The stock symbol.
            period (str): The time period for which to retrieve technical indicators.
                Valid periods: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max. Defaults to 3mo.

        Returns:
            str: JSON containing technical indicators.
        """
        try:
            logger.debug(f"Fetching technical indicators for {symbol}")
            indicators = yf.Ticker(symbol).history(period=period)
            return indicators.to_json(orient="index")
        except Exception as e:
            return f"Error fetching technical indicators for {symbol}: {e}"
