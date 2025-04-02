from datetime import datetime
from os import getenv
from typing import Dict, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import pytz
    import requests
except ImportError:
    raise ImportError("`requests` and `pytz` not installed. Please install using `pip install requests pytz`")


class CalComTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        event_type_id: Optional[int] = None,
        user_timezone: Optional[str] = None,
        get_available_slots: bool = True,
        create_booking: bool = True,
        get_upcoming_bookings: bool = True,
        reschedule_booking: bool = True,
        cancel_booking: bool = True,
        **kwargs,
    ):
        """Initialize the Cal.com toolkit.

        Args:
            api_key: Cal.com API key
            event_type_id: Default event type ID for bookings
            user_timezone: User's timezone in IANA format (e.g., 'Asia/Kolkata')
        """
        super().__init__(name="calcom", **kwargs)

        # Get credentials from environment if not provided
        self.api_key = api_key or getenv("CALCOM_API_KEY")
        event_type_str = getenv("CALCOM_EVENT_TYPE_ID")
        if event_type_id is not None:
            self.event_type_id = int(event_type_id)
        else:
            self.event_type_id = int(event_type_str) if event_type_str is not None else 0

        if not self.api_key:
            logger.error("CALCOM_API_KEY not set. Please set the CALCOM_API_KEY environment variable.")
        if not self.event_type_id:
            logger.error("CALCOM_EVENT_TYPE_ID not set. Please set the CALCOM_EVENT_TYPE_ID environment variable.")

        self.user_timezone = user_timezone or "America/New_York"

        # Register all methods
        if get_available_slots:
            self.register(self.get_available_slots)
        if create_booking:
            self.register(self.create_booking)
        if get_upcoming_bookings:
            self.register(self.get_upcoming_bookings)
        if reschedule_booking:
            self.register(self.reschedule_booking)
        if cancel_booking:
            self.register(self.cancel_booking)

    def _convert_to_user_timezone(self, utc_time: str) -> str:
        """Convert UTC time to user's timezone.

        Args:
            utc_time: UTC time string
            user_timezone: User's timezone (e.g., 'Asia/Kolkata')

        Returns:
            str: Formatted time in user's timezone
        """
        utc_dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
        user_tz = pytz.timezone(self.user_timezone)
        user_dt = utc_dt.astimezone(user_tz)
        return user_dt.strftime("%Y-%m-%d %H:%M %Z")

    def _get_headers(self, api_version: str = "2024-08-13") -> Dict[str, str]:
        """Get headers for Cal.com API requests.

        Args:
            api_version: Cal.com API version

        Returns:
            Dict[str, str]: Headers dictionary
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
            "cal-api-version": api_version,
            "Content-Type": "application/json",
        }

    def get_available_slots(
        self,
        start_date: str,
        end_date: str,
    ) -> str:
        """Get available time slots for booking.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            user_timezone: User's timezone
            event_type_id: Optional specific event type ID

        Returns:
            str: Available slots or error message
        """
        try:
            url = "https://api.cal.com/v2/slots/available"
            querystring = {
                "startTime": f"{start_date}T00:00:00Z",
                "endTime": f"{end_date}T23:59:59Z",
                "eventTypeId": str(self.event_type_id),
            }

            response = requests.get(url, headers=self._get_headers(), params=querystring)  # type: ignore
            if response.status_code == 200:
                slots = response.json()["data"]["slots"]
                available_slots = []
                for date, times in slots.items():
                    for slot in times:
                        user_time = self._convert_to_user_timezone(slot["time"])
                        available_slots.append(user_time)
                return f"Available slots: {', '.join(available_slots)}"
            return f"Failed to fetch slots: {response.text}"
        except Exception as e:
            logger.error(f"Error fetching available slots: {e}")
            return f"Error: {str(e)}"

    def create_booking(
        self,
        start_time: str,
        name: str,
        email: str,
    ) -> str:
        """Create a new booking.

        Args:
            start_time: Start time in YYYY-MM-DDTHH:MM:SSZ format
            name: Attendee's name
            email: Attendee's email

        Returns:
            str: Booking confirmation or error message
        """
        try:
            url = "https://api.cal.com/v2/bookings"
            start_time = datetime.fromisoformat(start_time).astimezone(pytz.utc).isoformat(timespec="seconds")
            payload = {
                "start": start_time,
                "eventTypeId": self.event_type_id,
                "attendee": {"name": name, "email": email, "timeZone": self.user_timezone},
            }

            response = requests.post(url, json=payload, headers=self._get_headers())
            if response.status_code == 201:
                booking_data = response.json()["data"]
                user_time = self._convert_to_user_timezone(booking_data["start"])
                return f"Booking created successfully for {user_time}. Booking uid: {booking_data['uid']}"
            return f"Failed to create booking: {response.text}"
        except Exception as e:
            logger.error(f"Error creating booking: {e}")
            return f"Error: {str(e)}"

    def get_upcoming_bookings(self, email: Optional[str] = None) -> str:
        """Get all upcoming bookings for an attendee.

        Args:
            email (str): Attendee's email [Optional]

        Returns:
            str: List of upcoming bookings or error message
        """
        try:
            url = "https://api.cal.com/v2/bookings"
            querystring = {"status": "upcoming"}
            if email:
                querystring["attendeeEmail"] = email

            response = requests.get(url, headers=self._get_headers(), params=querystring)
            if response.status_code == 200:
                bookings = response.json()["data"]
                if not bookings:
                    return "No upcoming bookings found."

                booking_info = []
                for booking in bookings:
                    user_time = self._convert_to_user_timezone(booking["start"])
                    booking_info.append(
                        f"uid: {booking['uid']}, Title: {booking['title']}, Time: {user_time}, Status: {booking['status']}"
                    )
                return "Upcoming bookings:\n" + "\n".join(booking_info)
            return f"Failed to fetch bookings: {response.text}"
        except Exception as e:
            logger.error(f"Error fetching upcoming bookings: {e}")
            return f"Error: {str(e)}"

    def reschedule_booking(
        self,
        booking_uid: str,
        new_start_time: str,
        reason: str,
    ) -> str:
        """Reschedule an existing booking.

        Args:
            booking_uid: Booking UID to reschedule
            new_start_time: New start time in YYYY-MM-DDTHH:MM:SSZ format
            reason: Reason for rescheduling
            user_timezone: User's timezone

        Returns:
            str: Rescheduling confirmation or error message
        """
        try:
            url = f"https://api.cal.com/v2/bookings/{booking_uid}/reschedule"
            new_start_time = datetime.fromisoformat(new_start_time).astimezone(pytz.utc).isoformat(timespec="seconds")
            payload = {"start": new_start_time, "reschedulingReason": reason}

            response = requests.post(url, json=payload, headers=self._get_headers())
            if response.status_code == 201:
                booking_data = response.json()["data"]
                user_time = self._convert_to_user_timezone(booking_data["start"])
                return f"Booking rescheduled to {user_time}. New booking uid: {booking_data['uid']}"
            return f"Failed to reschedule booking: {response.text}"
        except Exception as e:
            logger.error(f"Error rescheduling booking: {e}")
            return f"Error: {str(e)}"

    def cancel_booking(self, booking_uid: str, reason: str) -> str:
        """Cancel an existing booking.

        Args:
            booking_uid: Booking UID to cancel
            reason: Reason for cancellation

        Returns:
            str: Cancellation confirmation or error message
        """
        try:
            url = f"https://api.cal.com/v2/bookings/{booking_uid}/cancel"
            payload = {"cancellationReason": reason}

            response = requests.post(url, json=payload, headers=self._get_headers())
            if response.status_code == 200:
                return "Booking cancelled successfully."
            return f"Failed to cancel booking: {response.text}"
        except Exception as e:
            logger.error(f"Error cancelling booking: {e}")
            return f"Error: {str(e)}"
