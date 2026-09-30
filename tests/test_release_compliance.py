import unittest
import subprocess
import tempfile
from pathlib import Path

from scripts.release_compliance import (
    archive_homebrew_vcs_sources,
    cellar_coordinates,
    release_asset_names,
    validate_formula_records,
)


ROOT = Path(__file__).resolve().parents[1]


class ReleaseComplianceTests(unittest.TestCase):
    def test_extracts_formula_and_version_from_cellar_path(self):
        coordinates = cellar_coordinates(
            Path('/usr/local/Cellar/ffmpeg/7.1.1_3/lib/libavcodec.61.dylib')
        )

        self.assertEqual(coordinates, ('ffmpeg', '7.1.1_3'))
        self.assertIsNone(cellar_coordinates(Path('/usr/lib/libSystem.B.dylib')))

    def test_rejects_formula_record_without_corresponding_source(self):
        records = [
            {
                'name': 'ffmpeg',
                'version': '7.1.1_3',
                'formula': 'formulae/ffmpeg.rb',
                'receipt': 'receipts/ffmpeg.json',
                'licenses': ['licenses/ffmpeg/LICENSE.md'],
                'sources': [],
            }
        ]

        with self.assertRaisesRegex(RuntimeError, 'ffmpeg.*source'):
            validate_formula_records(records)

    def test_rejects_formula_record_with_missing_material_file(self):
        records = [
            {
                'name': 'ffmpeg',
                'formula': 'homebrew/ffmpeg/formula/ffmpeg.rb',
                'receipt': 'homebrew/ffmpeg/receipt/INSTALL_RECEIPT.json',
                'sources': ['homebrew-sources/ffmpeg.tar.xz'],
            }
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(RuntimeError, 'ffmpeg.*does not exist'):
                validate_formula_records(records, Path(temporary_directory))

    def test_release_asset_names_include_version_and_architecture(self):
        self.assertEqual(
            release_asset_names('v0.1.0', 'x86_64'),
            {
                'app_zip': 'yet-another-downloader-v0.1.0-macos-x86_64.zip',
                'dmg': 'yet-another-downloader-v0.1.0-macos-x86_64.dmg',
                'sources': 'yet-another-downloader-v0.1.0-corresponding-source.tar.gz',
                'checksums': 'SHA256SUMS.txt',
            },
        )

    def test_release_script_enforces_packaging_and_verification_steps(self):
        script = (ROOT / 'scripts/package-release.sh').read_text()

        for required in (
            'm3u8-bridge-release',
            '--fetch-sources',
            'cargo tauri build --bundles app',
            'codesign --verify --deep --strict',
            'ditto -c -k',
            'hdiutil create',
            'verify-release.sh',
        ):
            with self.subTest(required=required):
                self.assertIn(required, script)

        self.assertIn('if [ "${1:-}" = "--" ]; then', script)
        self.assertIn('shift', script)

    def test_release_script_keeps_homebrew_sources_out_of_app_bundle(self):
        script = (ROOT / 'scripts/package-release.sh').read_text()

        self.assertIn("--exclude='homebrew-sources/'", script)
        self.assertIn("--exclude='python-sources/'", script)

    def test_release_python_environment_ignores_user_site_packages(self):
        package_script = (ROOT / 'scripts/package-release.sh').read_text()
        compliance_script = (ROOT / 'scripts/release_compliance.py').read_text()

        self.assertIn('export PYTHONNOUSERSITE=1', package_script)
        self.assertIn('run(str(python), "-I", "-c", program)', compliance_script)

    def test_release_proxy_bypasses_loopback_services(self):
        package_script = (ROOT / 'scripts/package-release.sh').read_text()

        self.assertIn('127.0.0.1,localhost,::1', package_script)
        self.assertIn('export NO_PROXY=', package_script)
        self.assertIn('export no_proxy=', package_script)

    def test_release_collects_python_build_tool_sources_and_runtime_license(self):
        compliance_script = (ROOT / 'scripts/release_compliance.py').read_text()

        self.assertIn('python-sources', compliance_script)
        self.assertIn('pyinstaller-hooks-contrib', compliance_script)
        self.assertIn('lib/python{sys.version_info.major}.{sys.version_info.minor}', compliance_script)

    def test_archives_only_homebrew_git_checkouts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            source_root = output / 'homebrew-sources'
            checkout = source_root / 'example--git'
            downloads = source_root / 'downloads'
            api_cache = source_root / 'api'
            checkout.mkdir(parents=True)
            downloads.mkdir()
            api_cache.mkdir()
            (downloads / 'source.tar.gz').write_bytes(b'source archive')
            (api_cache / 'metadata.json').write_text('{}')
            (checkout / 'source.c').write_text('int main(void) { return 0; }\n')
            subprocess.run(['git', 'init', '-q', str(checkout)], check=True)
            subprocess.run(
                ['git', '-C', str(checkout), 'add', 'source.c'], check=True
            )
            subprocess.run(
                [
                    'git',
                    '-C',
                    str(checkout),
                    '-c',
                    'user.name=Release Test',
                    '-c',
                    'user.email=release-test@example.invalid',
                    'commit',
                    '-q',
                    '-m',
                    'fixture',
                ],
                check=True,
            )
            records = [
                {
                    'name': 'example',
                    'formula': 'homebrew/example/formula/example.rb',
                    'receipt': 'homebrew/example/receipt/INSTALL_RECEIPT.json',
                    'sources': ['homebrew-sources/example--git'],
                },
                {
                    'name': 'archive-example',
                    'formula': 'homebrew/archive/formula/archive.rb',
                    'receipt': 'homebrew/archive/receipt/INSTALL_RECEIPT.json',
                    'sources': ['homebrew-sources/downloads/source.tar.gz'],
                },
            ]

            vcs_records = archive_homebrew_vcs_sources(source_root, output, records)

            archive = source_root / 'example--git.tar.gz'
            self.assertTrue(archive.is_file())
            self.assertFalse(checkout.exists())
            self.assertTrue((downloads / 'source.tar.gz').is_file())
            self.assertFalse(api_cache.exists())
            self.assertEqual(
                records[0]['sources'], ['homebrew-sources/example--git.tar.gz']
            )
            self.assertEqual(
                records[1]['sources'], ['homebrew-sources/downloads/source.tar.gz']
            )
            self.assertEqual(vcs_records[0]['cache_directory'], 'example--git')

    def test_legal_staging_accepts_generated_release_materials(self):
        script = (ROOT / 'scripts/stage-legal.sh').read_text()

        self.assertIn('M3U8_BRIDGE_RELEASE_LEGAL_DIR', script)


if __name__ == '__main__':
    unittest.main()
