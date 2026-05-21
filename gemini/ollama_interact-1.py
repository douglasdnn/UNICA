import ollama

# Use the generate function for a one-off prompt
result = ollama.generate(model='cnmoro/gemma3-gaia-ptbr-4b:q8_0', prompt='Por que o céu é azul?')
print(result['response'])