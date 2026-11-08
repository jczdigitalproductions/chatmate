"""Build this dependency-free extension offline with an explicit file allowlist.

Produces a standard VSIX/OPC archive. No development caches, secrets, test state
or verifier files are traversed. Fixed ZIP timestamps make repeated builds equal.
"""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FILES = ('package.json', 'README.md', 'CHANGELOG.md', 'LICENSE',
         'src/extension.js', 'src/core.js', 'media/icon.svg', 'media/panel.css', 'media/panel.js')
NS = 'http://schemas.microsoft.com/developer/vsx-schema/2011'


def manifest(package):
    ET.register_namespace('', NS)
    def tag(name):
        return f'{{{NS}}}{name}'
    root = ET.Element(tag('PackageManifest'), Version='2.0.0')
    metadata = ET.SubElement(root, tag('Metadata'))
    ET.SubElement(metadata, tag('Identity'), Language='en-US', Id=package['name'],
                  Version=package['version'], Publisher=package['publisher'])
    for name, value in [('DisplayName', package['displayName']), ('Description', package['description']),
                        ('Categories', ','.join(package['categories'])), ('Tags', 'verification,testing,agents'),
                        ('GalleryFlags', 'Public'), ('License', 'extension/LICENSE')]:
        ET.SubElement(metadata, tag(name)).text = value
    properties = ET.SubElement(metadata, tag('Properties'))
    for name, value in [('Microsoft.VisualStudio.Code.Engine', package['engines']['vscode']),
                        ('Microsoft.VisualStudio.Code.ExtensionKind', ','.join(package['extensionKind'])),
                        ('Microsoft.VisualStudio.Code.ExtensionDependencies', ''),
                        ('Microsoft.VisualStudio.Code.ExtensionPack', ''),
                        ('Microsoft.VisualStudio.Code.ExecutesCode', 'true'),
                        ('Microsoft.VisualStudio.Services.GitHubFlavoredMarkdown', 'true')]:
        ET.SubElement(properties, tag('Property'), Id=name, Value=value)
    installation = ET.SubElement(root, tag('Installation'))
    ET.SubElement(installation, tag('InstallationTarget'), Id='Microsoft.VisualStudio.Code')
    ET.SubElement(root, tag('Dependencies'))
    assets = ET.SubElement(root, tag('Assets'))
    for name, path in [('Microsoft.VisualStudio.Code.Manifest', 'package.json'),
                       ('Microsoft.VisualStudio.Services.Content.Details', 'README.md'),
                       ('Microsoft.VisualStudio.Services.Content.Changelog', 'CHANGELOG.md'),
                       ('Microsoft.VisualStudio.Services.Content.License', 'LICENSE')]:
        ET.SubElement(assets, tag('Asset'), Type=name, Path=f'extension/{path}', Addressable='true')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def content_types():
    namespace = 'http://schemas.openxmlformats.org/package/2006/content-types'
    ET.register_namespace('', namespace)
    root = ET.Element(f'{{{namespace}}}Types')
    for extension, mime in [('json', 'application/json'), ('vsixmanifest', 'text/xml'),
                             ('js', 'application/javascript'), ('css', 'text/css'),
                             ('svg', 'image/svg+xml'), ('md', 'text/markdown')]:
        ET.SubElement(root, f'{{{namespace}}}Default', Extension=extension, ContentType=mime)
    ET.SubElement(root, f'{{{namespace}}}Override', PartName='/extension/LICENSE', ContentType='text/plain')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def build():
    package = json.loads((ROOT/'package.json').read_text(encoding='utf-8'))
    if package.get('dependencies'):
        raise ValueError('This offline builder supports only dependency-free runtime packages.')
    output = ROOT/f"{package['name']}-{package['version']}.vsix"
    entries = {'extension.vsixmanifest': manifest(package), '[Content_Types].xml': content_types()}
    entries.update({f'extension/{name}': (ROOT/name).read_bytes() for name in FILES})
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    with ZipFile(output) as archive:
        if set(archive.namelist()) != set(entries) or archive.testzip() is not None:
            raise ValueError('Archive validation failed.')
    print(f'Built {output.name}: {len(entries)} files, {output.stat().st_size} bytes')
    print('SHA-256:', hashlib.sha256(output.read_bytes()).hexdigest())
    return output


if __name__ == '__main__':
    build()
