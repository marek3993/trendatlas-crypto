"""exchangeInfo now exceeds 16 MiB; public downloads remain bounded."""
import io
import unittest
from unittest.mock import patch

from trendatlas_clean import fetch_data


class PublicResponseBoundTests(unittest.TestCase):
    def test_exchange_info_above_old_16_mib_limit_is_accepted(self):
        body=b' '*(18*1024*1024)
        with patch.object(fetch_data,'urlopen',return_value=io.BytesIO(body)):
            self.assertEqual(fetch_data._bytes('https://example.invalid/exchangeInfo'),body)

    def test_response_over_64_mib_is_rejected(self):
        self.assertEqual(fetch_data.MAX_PUBLIC_RESPONSE_BYTES,64*1024*1024)
        with patch.object(fetch_data,'urlopen',return_value=io.BytesIO(b' '*(64*1024*1024+1))):
            with self.assertRaisesRegex(fetch_data.DataUnavailable,'size bound'):
                fetch_data._bytes('https://example.invalid/oversized')


if __name__=='__main__':unittest.main()
