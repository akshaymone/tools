import re
from xml.etree import ElementTree as ET

content = """
<p:sp>
  <p:txBody>
    <a:p>
      <a:r>
        <a:rPr b="1" i="1"/>
        <a:t>Bold and Italic</a:t>
      </a:r>
      <a:r>
        <a:t> Normal text</a:t>
      </a:r>
    </a:p>
    <a:p>
       <a:r><a:t>Second paragraph</a:t></a:r>
    </a:p>
  </p:txBody>
</p:sp>
"""

# Let's mock a namespace dict
ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}

def parse_text_body(txBody_elem):
    paras = []
    for p_elem in txBody_elem.findall('.//a:p', ns):
        para_text = ""
        for r_elem in p_elem.findall('.//a:r', ns):
            t_elem = r_elem.find('./a:t', ns)
            if t_elem is None or not t_elem.text:
                continue
            text = t_elem.text
            rPr = r_elem.find('./a:rPr', ns)
            if rPr is not None:
                if rPr.get('b') == '1':
                    text = f"**{text}**"
                if rPr.get('i') == '1':
                    text = f"*{text}*"
            para_text += text
        if para_text.strip():
            paras.append(para_text)
    return paras

root = ET.fromstring(content)
for tx in root.findall('.//p:txBody', ns):
    print(parse_text_body(tx))
