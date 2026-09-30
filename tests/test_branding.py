import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCT_NAME = 'yet another downloader'


class BrandingTests(unittest.TestCase):
    def test_desktop_and_extension_use_product_name(self):
        tauri = json.loads((ROOT / 'src-tauri/tauri.conf.json').read_text())
        manifest = json.loads((ROOT / 'apps/chrome-extension/public/manifest.json').read_text())

        self.assertEqual(tauri['package']['productName'], PRODUCT_NAME)
        self.assertEqual(tauri['tauri']['windows'][0]['title'], PRODUCT_NAME)
        self.assertEqual(manifest['name'], f'{PRODUCT_NAME} capture')
        self.assertEqual(manifest['action']['default_title'], PRODUCT_NAME)
        self.assertIn(PRODUCT_NAME, manifest['description'])

    def test_desktop_build_stages_legal_notices(self):
        tauri = json.loads((ROOT / 'src-tauri/tauri.conf.json').read_text())

        self.assertIn('pnpm run stage:legal', tauri['build']['beforeBuildCommand'])
        self.assertIn('resources/legal', tauri['tauri']['bundle']['resources'])

    def test_user_visible_sources_use_product_name(self):
        expected_sources = [
            'README.md',
            'apps/desktop/index.html',
            'apps/desktop/src/main.tsx',
            'apps/chrome-extension/index.html',
            'apps/chrome-extension/src/desktop-launch.ts',
            'packages/ui/src/index.tsx',
            'docs/architecture.md',
            'docs/deployment.md',
            'docs/operation.md',
            'docs/testing.md',
        ]

        for source in expected_sources:
            with self.subTest(source=source):
                self.assertIn(PRODUCT_NAME, (ROOT / source).read_text())

    def test_compatibility_identifiers_remain_stable(self):
        tauri = json.loads((ROOT / 'src-tauri/tauri.conf.json').read_text())
        server = (ROOT / 'engine/m3u8_bridge/server.py').read_text()

        self.assertEqual(tauri['tauri']['bundle']['identifier'], 'io.github.shumybest.yet-another-downloader')
        self.assertEqual(tauri['tauri']['bundle']['externalBin'], ['binaries/m3u8-bridge-engine'])
        self.assertIn("'Application Support' / 'm3u8-bridge'", server)
        self.assertIn("M3U8_BRIDGE_PORT', '8765'", server)


if __name__ == '__main__':
    unittest.main()
