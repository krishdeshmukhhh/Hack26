"""Design system tokens for Curio.

Only the tokens our widgets
actually reference are included — not a blanket copy.
"""


class DS:
    class Colors:
        # Backgrounds
        panel_bg = "#1a1a1a"
        surface = "#2a2a2a"

        # Text
        text_primary = "#e0e0e0"
        text_secondary = "#888888"
        text_white = "#ffffff"

        # Accents
        accent_blue = "#4a9eff"
        accent_green = "#4ade80"
        accent_amber = "#f59e0b"

        # Waveform
        waveform_bar = "#4a9eff"

        # Transcript
        interim_text = "#888888"
        final_text = "#ffffff"

        # Status banner
        error_bg = "#8B0000"
        warning_bg = "#8B6508"
        info_bg = "#1a3a5c"

        # Error
        error_red = "#EA5455"

        # Companion state colors
        companion_idle = "#4a9eff"       # blue
        companion_listening = "#4a9eff"  # blue (opacity changes)
        companion_processing = "#f5a623" # amber
        companion_responding = "#34d399" # green
        companion_error = "#ef4444"      # red

        # Borders
        border = "#444444"

    class CornerRadius:
        large = 16  # panel
        medium = 12
        small = 8   # banner, buttons
        xs = 4      # combo box

    class Spacing:
        xs = 4
        sm = 8
        md = 12
        lg = 16
        xl = 24

    class Fonts:
        size_sm = 12
        size_md = 14
        size_lg = 16
