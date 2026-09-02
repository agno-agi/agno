# Google Maps API Authentication Fix

## Problem Overview

The `places_v1.PlacesClient()` from Google Maps Places API v1 requires authentication credentials. By default, it tries to use Google Cloud's Application Default Credentials (ADC), which causes the following error:

```
google.auth.exceptions.DefaultCredentialsError: Your default credentials were not found.
```

## Solution Implemented

We fixed this by explicitly providing API key credentials to the Places client instead of relying on ADC.

## Code Changes

### Import Statements Added

```python
from google.auth import api_key as api_key_credentials
```

### Modified `__init__` Method

**Before:**
```python
self.places_client = places_v1.PlacesClient()
```

**After:**
```python
# Create credentials with API key
credentials = api_key_credentials.Credentials(self.api_key)

# Initialize places client with credentials
self.places_client = places_v1.PlacesClient(credentials=credentials)
```

## How It Works

1. **API Key Retrieval**: The API key is retrieved from environment variables or passed directly:
   ```python
   self.api_key = key or getenv("GOOGLE_MAPS_API_KEY")
   ```

2. **Credentials Object Creation**: Convert the API key string into a credentials object:
   ```python
   credentials = api_key_credentials.Credentials(self.api_key)
   ```

3. **Client Initialization**: Pass the credentials to the Places client:
   ```python
   self.places_client = places_v1.PlacesClient(credentials=credentials)
   ```

## Environment Setup

Make sure your `.env` file contains:

```env
GOOGLE_MAPS_API_KEY=your_actual_google_maps_api_key_here
GOOGLE_API_KEY=your_gemini_api_key_here
```

## API Requirements

Ensure the following APIs are enabled in your Google Cloud Console:

1. **Places API (New)** - For `places_v1.PlacesClient()`
2. **Geocoding API** - For address geocoding
3. **Directions API** - For route planning
4. **Distance Matrix API** - For distance calculations
5. **Elevation API** - For elevation data
6. **Time Zone API** - For timezone information
7. **Address Validation API** - For address validation

### Enable APIs

Visit: [Google Cloud Console - APIs & Services](https://console.cloud.google.com/apis/library)

Search for each API and click "Enable".

## Verifying the Fix

Run your agent:

```bash
python agent_test.py
```

You should no longer see the `DefaultCredentialsError`.

## Expected Behavior

The agent will now:
- ✅ Successfully authenticate with Google Maps APIs
- ✅ Search for places using Places API v1
- ✅ Get directions and route information
- ✅ Provide travel time estimates
- ✅ Suggest transportation options

## Troubleshooting

### Issue: Still Getting Authentication Error

**Solution**: Verify your API key is correct and has the necessary permissions.

```python
# Test your API key
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GOOGLE_MAPS_API_KEY")
print(f"API Key loaded: {api_key[:10]}..." if api_key else "No API key found")
```

### Issue: API Key Invalid

**Solution**: 
1. Go to [Google Cloud Console - Credentials](https://console.cloud.google.com/apis/credentials)
2. Create a new API key or verify existing one
3. Ensure API key restrictions allow your APIs
4. Update your `.env` file

### Issue: Quota Exceeded

**Solution**: Check your quota limits in Google Cloud Console and enable billing if necessary.

## Alternative Authentication Methods

### Method 1: API Key (Current Implementation)
✅ Simple and straightforward  
✅ Works for most use cases  
⚠️ May have limitations with some advanced features

### Method 2: Service Account (Production Recommended)

If you need more advanced features:

1. Create a service account in Google Cloud Console
2. Download the JSON key file
3. Update code:

```python
from google.oauth2 import service_account

def __init__(self, key: Optional[str] = None, credentials_path: Optional[str] = None, **kwargs):
    self.api_key = key or getenv("GOOGLE_MAPS_API_KEY")
    self.client = googlemaps.Client(key=self.api_key)
    
    creds_path = credentials_path or getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path:
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        self.places_client = places_v1.PlacesClient(credentials=credentials)
```

4. Set environment variable:
```env
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account-key.json
```

## Security Best Practices

1. **Never commit API keys** to version control
2. **Use `.env` files** for local development
3. **Use environment variables** for production
4. **Restrict API keys** by IP address or referrer if possible
5. **Enable billing alerts** to monitor usage
6. **Rotate keys regularly** for security

## Additional Resources

- [Google Maps Platform Documentation](https://developers.google.com/maps/documentation)
- [Places API v1 Documentation](https://developers.google.com/maps/documentation/places/web-service/overview)
- [Google Cloud Authentication Guide](https://cloud.google.com/docs/authentication)
- [API Key Best Practices](https://cloud.google.com/docs/authentication/api-keys)

## Support

If you encounter any issues:
1. Check Google Cloud Console for API status
2. Verify all required APIs are enabled
3. Check quota limits and billing status
4. Review error logs for specific error messages

---

**Last Updated**: October 29, 2025  
**Status**: ✅ Working Solution