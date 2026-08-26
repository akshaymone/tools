import torch
from PIL import Image
from colpali_engine.models import ColIdefics3Processor
processor = ColIdefics3Processor.from_pretrained("vidore/colSmol-500M")
img = Image.new('RGB', (224, 224), color = 'red')
inputs = processor.process_images([img])
print("process_images output keys:", inputs.keys())
print("input_ids shape:", inputs.get("input_ids", torch.tensor([])).shape)
queries = processor.process_queries(["hello world"])
print("process_queries output keys:", queries.keys())
print("input_ids shape:", queries.get("input_ids", torch.tensor([])).shape)
