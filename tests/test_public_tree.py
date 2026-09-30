import tempfile
import unittest
from pathlib import Path

from scripts.check_public_tree import scan_paths


class PublicTreeScannerTests(unittest.TestCase):
    def test_rejects_credentials_personal_paths_and_generated_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('API_KEY=secret\n')
            (root / 'notes.md').write_text('/' + 'Users/alice/private/video.mp4\n')
            (root / 'release.zip').write_bytes(b'zip')

            findings = scan_paths(root, [Path('.env'), Path('notes.md'), Path('release.zip')])

        kinds = {finding.kind for finding in findings}
        self.assertEqual(kinds, {'sensitive-filename', 'personal-path', 'generated-artifact'})

    def test_accepts_documented_placeholders_and_source_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env.example').write_text('API_TOKEN=replace-me\n')
            (root / 'README.md').write_text('Use Authorization: Bearer <token> on 127.0.0.1.\n')
            (root / 'app.py').write_text("URL = 'https://media.example.test/video.m3u8'\n")

            findings = scan_paths(root, [Path('.env.example'), Path('README.md'), Path('app.py')])

        self.assertEqual(findings, [])


if __name__ == '__main__':
    unittest.main()
