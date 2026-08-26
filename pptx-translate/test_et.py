import xml.etree.ElementTree as ET

xml_content = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" 
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" 
       xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
       xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main">
  <mc:AlternateContent>
    <mc:Choice>
      <p:cSld><a:t>Hello</a:t></p:cSld>
    </mc:Choice>
  </mc:AlternateContent>
</p:sld>"""

with open('test_ns.xml', 'w') as f:
    f.write(xml_content)

tree = ET.parse('test_ns.xml')
tree.write('test_ns_out.xml', encoding='utf-8', xml_declaration=True)

with open('test_ns_out.xml') as f:
    print(f.read())
