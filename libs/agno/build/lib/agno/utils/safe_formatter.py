import string


class SafeFormatter(string.Formatter):
    def get_value(self, key, args, kwargs):
        """Handle missing keys by returning '{key}'."""
        if key not in kwargs:
            return f"{key}"
        return kwargs[key]

    def format_field(self, value, format_spec):
        """
        If Python sees something like 'somekey:"stuff"', it tries to parse
        it as a format spec and might raise ValueError. We catch it here
        and just return the literal placeholder.
        """
        if not format_spec:
            return super().format_field(value, format_spec)

        try:
            return super().format_field(value, format_spec)
        except ValueError:
            # On invalid format specifiers, keep them literal
            return f"{{{value}:{format_spec}}}"
