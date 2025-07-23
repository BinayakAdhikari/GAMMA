import torch
from patchGeneration.unixcoder import UniXcoder
import os
import argparse
import subprocess
import base64
import time

# Initialize UniXcoder model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = UniXcoder("microsoft/unixcoder-base")
model.to(device)

def insert_mask_token_multiline(code: str, start_line: int, end_line: int, context_before: int = 2, context_after: int = 2) -> str:
    """
    Extracts a context window around a buggy line range and inserts <mask0> in its place.
    start_line and end_line are 0-indexed.
    """
    lines = code.splitlines()
    total_lines = len(lines)

    if not (0 <= start_line < total_lines and 0 <= end_line < total_lines and start_line <= end_line):
        print(f"Warning: Invalid line range {start_line}-{end_line}. No masking applied.")
        return code, 0

    context_start = max(0, start_line - context_before)
    context_end = min(total_lines - 1, end_line + context_after)

    # The code before the buggy region
    pre_context = lines[context_start:start_line]
    # The code after the buggy region
    post_context = lines[end_line + 1:context_end + 1]

    # Combine to form the masked code for the model
    masked_code_list = pre_context + ["<mask0>"] + post_context
    
    return "\n".join(masked_code_list)

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
        patched_line = prediction.replace(target_line_placeholder, '')
        res.append(patched_line.strip())
    return res

def test_and_validate_patches(file_path: str, start_line_1_indexed: int, end_line_1_indexed: int, test_command: str):
    """
    Generates patches for a buggy file and validates them using a provided test command.
    """
    try:
        with open(file_path, 'r') as f:
            original_code = f.read()
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
        return

    print(f"--- Read {len(original_code.splitlines())} lines from {file_path} ---")
    print(f"Buggy lines (1-indexed): {start_line_1_indexed}-{end_line_1_indexed}\n")

    start_line_0 = start_line_1_indexed - 1
    end_line_0 = end_line_1_indexed - 1

    masked_code = insert_mask_token_multiline(original_code, start_line_0, end_line_0)
    print("--- Masked Code Snippet for model ---")
    print(masked_code)
    print("\n")

    print("--- Generating Patches (This may take a moment) ---")
    try:
        patches = fill_mask(masked_code)
        if not patches:
            print("No patches generated.")
            return

        print(f"--- Generated {len(patches)} Patches. Now validating... ---")

        lines = original_code.splitlines()
        validated_patches = 0
        
        original_file_backup_path = f"{file_path}.bak"
        if os.path.exists(original_file_backup_path):
            os.remove(original_file_backup_path)
            
        os.rename(file_path, original_file_backup_path)
        
        try:
            for idx, patch in enumerate(patches):
                print(f"--- Testing Patch {idx + 1}: {patch} ---")

                # Replace the buggy line range with the patch
                patched_lines = lines[:start_line_0] + [patch] + lines[end_line_0 + 1:]
                with open(file_path, 'w') as f:
                    f.write('\n'.join(patched_lines))

                result = subprocess.run(test_command, shell=True, capture_output=True, text=True)

                if result.returncode == 0:
                    print(f"PASSED: Patch {idx + 1} passed the test suite.")
                    validated_patches += 1
                else:
                    print(f"FAILED: Patch {idx + 1} failed the test suite.")
            
        finally:
            time.sleep(0.2) # Add a small delay to allow file locks to be released
            if os.path.exists(original_file_backup_path):
                os.replace(original_file_backup_path, file_path)

        print(f"\n--- Validation Summary ---")
        print(f"{validated_patches} out of {len(patches)} patches passed the test suite.")

    except Exception as e:
        print(f"An error occurred: {e}")
        time.sleep(0.2)
        if os.path.exists(original_file_backup_path):
            os.replace(original_file_backup_path, file_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and test patches for a buggy file.")
    parser.add_argument("file_path", help="The path to the buggy Python file.")
    parser.add_argument("start_line", type=int, help="The 1-indexed starting line number of the buggy code.")
    parser.add_argument("end_line", type=int, help="The 1-indexed ending line number of the buggy code.")
    parser.add_argument("test_command", help="The base64 encoded shell command to run the test suite.")
    
    args = parser.parse_args()

    decoded_test_command = base64.b64decode(args.test_command).decode('utf-8')

    print("\nStarting patch generation and validation...\n")
    test_and_validate_patches(args.file_path, args.start_line, args.end_line, decoded_test_command)
    print("\nProcess finished.")