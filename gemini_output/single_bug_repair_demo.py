import torch
from ..patchGeneration.unixcoder import UniXcoder
import os

# Initialize UniXcoder model (same as in unixcoder_repair.py)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = UniXcoder("microsoft/unixcoder-base")
model.to(device)

def insert_mask_token(code: str, buggy_line_num: int, context_before: int = 2, context_after: int = 2) -> str:
    """
    Extracts a context window around the buggy line and inserts <mask0> in place of the buggy line.
    buggy_line_num is 0-indexed.
    """
    lines = code.splitlines()
    total_lines = len(lines)

    if not (0 <= buggy_line_num < total_lines):
        print(f"Warning: Invalid line number {buggy_line_num}. No masking applied.")
        return code

    start_index = max(0, buggy_line_num - context_before)
    end_index = min(total_lines - 1, buggy_line_num + context_after)

    context_lines = lines[start_index : end_index + 1]
    
    # Calculate the new 0-indexed position of the buggy line within the context_lines list
    buggy_line_in_context = buggy_line_num - start_index
    
    context_lines[buggy_line_in_context] = "<mask0>"
    
    return "\n".join(context_lines)

def fill_mask(code_str, target_line_placeholder="<mask0>"):
    """
    Uses the UniXcoder model to fill the masked token in the code_str.
    """
    tokens_ids = model.tokenize([code_str], max_length=512, mode="<encoder-decoder>")
    source_ids = torch.tensor(tokens_ids).to(device)
    prediction_ids = model.generate(source_ids, decoder_only=False, beam_size=25, max_length=128)
    predictions = model.decode(prediction_ids)
    
    res = []
    for prediction in predictions[0]:
        # Replace the mask token in the original code_str with the prediction
        # The prediction itself might contain the mask token, so remove it from prediction first
        patched_line = prediction.replace(target_line_placeholder, '')
        
        # Reconstruct the full code with the patched line
        # This part assumes the original code_str had the mask token inserted
        # and we are replacing that specific masked line.
        # For simplicity in this demo, we'll just return the predicted line.
        # In a real scenario, you'd re-insert this line into the original code structure.
        res.append(patched_line.strip())
    return res

def repair_single_snippet(code_snippet: str, buggy_line_num_1_indexed: int):
    """
    Masks a line in a code snippet and generates patches using UniXcoder.
    buggy_line_num_1_indexed is 1-indexed (as typically seen by users).
    """
    print("--- Original Code Snippet ---")
    print(code_snippet)
    print(f"Buggy line (1-indexed): {buggy_line_num_1_indexed}\n")

    # Convert to 0-indexed for internal use
    buggy_line_num_0_indexed = buggy_line_num_1_indexed - 1

    masked_code = insert_mask_token(code_snippet, buggy_line_num_0_indexed, context_before=2, context_after=2)
    print("--- Masked Code Snippet ---")
    print(masked_code)
    print("\n")

    print("--- Generating Patches (This may take a moment) ---")
    try:
        patches = fill_mask(masked_code)
        if patches:
            print("--- Generated Patches ---")
            for idx, patch in enumerate(patches):
                print(f"Patch {idx + 1}: {patch}")
        else:
            print("No patches generated for this snippet.")
    except Exception as e:
        print(f"An error occurred during patch generation: {e}")

if __name__ == "__main__":
    # Example Usage:
    # Replace this with your actual buggy code snippet and line number
    example_buggy_code = """
x = 5
y = 10
result = x - y # This is the buggy line
"""
    example_buggy_line = 3 # Line 3 is 'result = x - y # This is the buggy line'

    print("\nStarting single bug repair demo...\n")
    repair_single_snippet(example_buggy_code, example_buggy_line)
    print("\nDemo finished.")