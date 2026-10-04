"""Checksums for Italian/EU identifiers. Used to detect, and to generate valid test data."""

from __future__ import annotations

_CF_ODD_DIGITS = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21]
_CF_ODD = {
    **{str(i): v for i, v in enumerate(_CF_ODD_DIGITS)},
    **{chr(65 + i): v for i, v in enumerate(_CF_ODD_DIGITS)},
    **dict(zip("KLMNOPQRSTUVWXYZ", [2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24, 23])),
}
_CF_EVEN = {**{str(i): i for i in range(10)}, **{chr(65 + i): i for i in range(26)}}


def cf_check_char(first_fifteen: str) -> str:
    total = 0
    for position, char in enumerate(first_fifteen.upper()):
        total += _CF_ODD[char] if position % 2 == 0 else _CF_EVEN[char]
    return chr(65 + total % 26)


def is_valid_cf(value: str) -> bool:
    value = value.upper()
    if len(value) != 16 or not value.isalnum() or not value.isascii():
        return False
    try:
        return cf_check_char(value[:15]) == value[15]
    except KeyError:
        return False


def piva_check_digit(first_ten: str) -> int:
    total = 0
    for position, char in enumerate(first_ten):
        digit = int(char)
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return (10 - total % 10) % 10


def is_valid_piva(value: str) -> bool:
    return len(value) == 11 and value.isdigit() and piva_check_digit(value[:10]) == int(value[10])


IBAN_LENGTHS = {
    "IT": 27, "SM": 27, "VA": 22, "DE": 22, "FR": 27, "ES": 24, "GB": 22, "CH": 21,
    "NL": 18, "BE": 16, "LU": 20, "AT": 20, "PT": 25, "IE": 22,
}  # fmt: skip


def _mod97(text: str) -> int:
    digits = "".join(str(int(char, 36)) for char in text)
    return int(digits) % 97


def iban_check_digits(country: str, bban: str) -> str:
    return f"{98 - _mod97(bban.upper() + country.upper() + '00'):02d}"


def is_valid_iban(compact: str) -> bool:
    compact = compact.upper()
    if len(compact) < 15 or not compact.isalnum() or not compact.isascii():
        return False
    return _mod97(compact[4:] + compact[:4]) == 1
