"""
HTML utility functions for generating authentication pages.
"""

def get_common_styles():
    """
    Returns common CSS styles used across authentication pages.
    """
    return """
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background-color: #f5f5f5;
            color: #333;
        }
        .container {
            text-align: center;
            padding: 2rem;
            background: white;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
            max-width: 500px;
        }
        h1 {
            margin-bottom: 1rem;
        }
        .loader {
            border: 5px solid #f3f3f3;
            border-radius: 50%;
            border-top: 5px solid #3498db;
            width: 50px;
            height: 50px;
            margin: 20px auto;
            animation: spin 2s linear infinite;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .message {
            margin-top: 20px;
            font-size: 16px;
        }
        .success-icon {
            color: #5cb85c;
            font-size: 48px;
            margin-bottom: 20px;
        }
        .error-icon {
            color: #d9534f;
            font-size: 48px;
            margin-bottom: 20px;
        }
    """

def get_loading_page(redirect_params):
    """
    Returns the HTML for the loading page.
    
    Returns:
        str: HTML content for the loading page
    """
    return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Agno CLI Authentication</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                    background-color: #f5f5f5;
                    color: #333;
                }}
                .container {{
                    text-align: center;
                    padding: 2rem;
                    background: white;
                    border-radius: 8px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                    max-width: 500px;
                }}
                .loader {{
                    border: 4px solid #f3f3f3;
                    border-radius: 50%;
                    border-top: 4px solid #3498db;
                    width: 40px;
                    height: 40px;
                    margin: 20px auto;
                    animation: spin 1s linear infinite;
                }}
                @keyframes spin {{
                    0% {{ transform: rotate(0deg); }}
                    100% {{ transform: rotate(360deg); }}
                }}
                .status {{
                    margin-top: 20px;
                    font-weight: 500;
                }}
            </style>
            <script>
                // Redirect to result page after delay
                setTimeout(function() {{
                    window.location.href = "{redirect_params}";
                }}, 2000); // 2 second delay
            </script>
        </head>
        <body>
            <div class="container">
                <h1>Processing</h1>
                <div class="loader"></div>
                <p class="status">Please wait while we authenticate your CLI...</p>
            </div>
        </body>
        </html>
        """

def get_success_page():
    """
    Returns the HTML for the success page.
    
    Returns:
        str: HTML content for the success page
    """
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Agno CLI Authentication</title>
        <style>
            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: #f5f5f5;
                color: #333;
            }
            .container {
                text-align: center;
                padding: 2rem;
                background: white;
                border-radius: 8px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                max-width: 500px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Authentication Successful!</h1>
            <p>Your CLI has been successfully authenticated with Agno.</p>
            <p>You can close this window now.</p>
        </div>
    </body>
    </html>
    """

def get_error_page(message="Authentication failed. Please try again."):
    """
    Returns the HTML for the error page.
    
    Args:
        message: The error message to display
        
    Returns:
        str: HTML content for the error page
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Agno CLI Authentication</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: #f5f5f5;
                color: #333;
            }}
            .container {{
                text-align: center;
                padding: 2rem;
                background: white;
                border-radius: 8px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                max-width: 500px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Authentication Failed</h1>
            <p>{message}</p>
        </div>
    </body>
    </html>
    """

def get_no_cookies_error_page():
    """
    Returns the HTML for the error page when no cookies are found.
    
    Returns:
        str: HTML content for the no cookies error page
    """
    return get_error_page("No cookies were found. Please ensure you're logged in to Agno and try again.")

def get_no_auth_token_error_page():
    """
    Returns the HTML for the error page when no auth token is found.
    
    Returns:
        str: HTML content for the no auth token error page
    """
    return get_error_page("Auth cookie not found. Please try again or contact support.")

