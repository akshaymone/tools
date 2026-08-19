import xml.etree.ElementTree as ET

xml_content = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" 
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" 
       xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
       xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main"
       mc:Ignorable="p14">
  <mc:AlternateContent>
    <mc:Choice>
      <p:cSld><a:t>Hello</a:t></p:cSld>
    </mc:Choice>
  </mc:AlternateContent>
</p:sld>"""

with open('test_ns.xml', 'w') as f:
    f.write(xml_content)

namespaces = dict([node for _, node in ET.iterparse('test_ns.xml', events=['start-ns'])])
for ns, url in namespaces.items():
    ET.register_namespace(ns, url)

tree = ET.parse('test_ns.xml')
root = tree.getroot()

# Force write the unused namespaces
for ns, url in namespaces.items():
    attr_name = f"xmlns:{ns}" if ns else "xmlns"
    # ElementTree strips the xmlns attributes during parsing, so we re-add them
    # But wait, ET might output it twice? Let's see.
    root.set(attr_name, url)

# Wait, if we use root.set('xmlns:p14', url), ET will output it as a normal attribute,
# but it might escape the colon? In Python 3.8+ it handles it gracefully!
tree.write('test_ns_out.xml', encoding='utf-8', xml_declaration=True)

with open('test_ns_out.xml') as f:
    print(f.read())
