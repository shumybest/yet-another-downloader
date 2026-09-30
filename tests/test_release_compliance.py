import unittest
import hashlib
import subprocess
import tempfile
from pathlib import Path

import scripts.release_compliance as release_compliance

from scripts.release_compliance import (
    archive_homebrew_vcs_sources,
    cellar_coordinates,
    download_formula_primary_source,
    is_ignorable_homebrew_fetch_failure,
    primary_source_matches_formula,
    release_asset_names,
    reset_output_preserving_source_cache,
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

    def test_preserves_homebrew_source_cache_between_release_attempts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / 'compliance'
            cache_file = output / 'homebrew-sources/downloads/source.tar.gz'
            cache_file.parent.mkdir(parents=True)
            cache_file.write_bytes(b'source')
            (output / 'stale-manifest.json').write_text('{}')

            reset_output_preserving_source_cache(output, True)

            self.assertEqual(cache_file.read_bytes(), b'source')
            self.assertFalse((output / 'stale-manifest.json').exists())

    def test_allows_only_known_non_build_homebrew_test_resource_failure(self):
        formula = '''
class Libogg < Formula
  url "https://example.test/libogg.tar.gz"
  sha256 "deadbeef"
  resource("oggfile") do
    url "https://example.test/Example.ogg"
  end
  def install
    system "make", "install"
  end
  test do
    testpath.install resource("oggfile")
  end
end
'''
        log = 'Resource libogg--oggfile\nError: Resource reports different checksum'

        self.assertTrue(is_ignorable_homebrew_fetch_failure('libogg', formula, log))
        self.assertTrue(
            is_ignorable_homebrew_fetch_failure(
                'libvorbis', formula.replace('Libogg', 'Libvorbis'), log.replace('libogg', 'libvorbis')
            )
        )
        self.assertFalse(is_ignorable_homebrew_fetch_failure('other', formula, log))
        build_resource_formula = formula.replace(
            'system "make", "install"',
            'resource("oggfile").stage\n    system "make", "install"',
        )
        self.assertFalse(
            is_ignorable_homebrew_fetch_failure(
                'libogg', build_resource_formula, log
            )
        )

    def test_primary_source_checksum_accepts_git_checkout_and_checks_archive(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            checkout = root / 'source--git'
            checkout.mkdir()
            archive = root / 'source.tar.gz'
            archive.write_bytes(b'source')
            digest = hashlib.sha256(b'source').hexdigest()

            self.assertTrue(primary_source_matches_formula('sha256 "deadbeef"', checkout))
            self.assertTrue(
                primary_source_matches_formula(f'sha256 "{digest}"', archive)
            )
            self.assertFalse(
                primary_source_matches_formula('sha256 "' + ('0' * 64) + '"', archive)
            )

    def test_downloads_simple_formula_source_with_verified_checksum(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            upstream = root / 'upstream.tar.gz'
            upstream.write_bytes(b'source archive')
            digest = hashlib.sha256(upstream.read_bytes()).hexdigest()
            formula = f'''\
class Example < Formula
  url "{upstream.as_uri()}"
  sha256 "{digest}"
end
'''

            downloaded = download_formula_primary_source(
                'example', '1.0.0', formula, root / 'cache'
            )

            self.assertEqual(downloaded.read_bytes(), upstream.read_bytes())
            with self.assertRaisesRegex(RuntimeError, 'complex formula'):
                download_formula_primary_source(
                    'example',
                    '1.0.0',
                    formula.replace('end', 'resource("fixture") do\n  end\nend'),
                    root / 'other-cache',
                )

    def test_recovers_failed_formula_resource_from_installed_prefix_with_verified_checksum(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            prefix = root / 'Cellar/tesseract/5.5.1'
            installed = prefix / 'share/tessdata/snum.traineddata'
            installed.parent.mkdir(parents=True)
            installed.write_bytes(b'verified trained data')
            digest = hashlib.sha256(installed.read_bytes()).hexdigest()
            formula = f'''\
class Tesseract < Formula
  url "https://example.test/tesseract.tar.gz"
  sha256 "{'0' * 64}"
  resource "snum" do
    url "https://example.test/Training%20Tesseract/snum.traineddata"
    sha256 "{digest}"
  end
end
'''
            log = '''\
✘ Resource tesseract--snum
Error: Failed to download resource "tesseract--snum"
Download failed: https://example.test/snum.traineddata
curl: (56) The requested URL returned error: 404
'''

            recovered = release_compliance.recover_failed_formula_resources(
                'tesseract', '5.5.1', formula, log, prefix, root / 'cache'
            )

            self.assertEqual(len(recovered), 1)
            self.assertEqual(recovered[0].read_bytes(), installed.read_bytes())
            self.assertEqual(hashlib.sha256(recovered[0].read_bytes()).hexdigest(), digest)

            installed.write_bytes(b'wrong resource')
            self.assertEqual(
                release_compliance.recover_failed_formula_resources(
                    'tesseract', '5.5.1', formula, log, prefix, root / 'other-cache'
                ),
                [],
            )

    def test_legal_staging_accepts_generated_release_materials(self):
        script = (ROOT / 'scripts/stage-legal.sh').read_text()

        self.assertIn('M3U8_BRIDGE_RELEASE_LEGAL_DIR', script)


if __name__ == '__main__':
    unittest.main()
