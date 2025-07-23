import torch
from transformers import RobertaTokenizer, RobertaForMaskedLM
import os
import argparse
import subprocess
import base64
import time

# Initialize CodeBERT model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
tokenizer = RobertaTokenizer.from_pretrained("microsoft/codebert-base")
model = RobertaForMaskedLM.from_pretrained("microsoft/codebert-base")
model.to(device)

def insert_mask_token_multiline(code: str, start_line: int, end_line: int, context_before: int = 2, context_after: int = 2) -> str:
    """
    Extracts a context window and replaces the buggy line range with a mask token.
    """
    lines = code.splitlines()
    total_lines = len(lines)

    if not (0 <= start_line < total_lines and 0 <= end_line < total_lines and start_line <= end_line):
        print(f"Warning: Invalid line range {start_line}-{end_line}. No masking applied.")
        return ""

    context_start = max(0, start_line - context_before)
    context_end = min(total_lines - 1, end_line + context_after)

    pre_context = lines[context_start:start_line]
    post_context = lines[end_line + 1:context_end + 1]

    # For CodeBERT, the mask is '<mask>'
    masked_code_list = pre_context + ["<mask>"] + post_context
    
    return "\n".join(masked_code_list)

def fill_mask(code_str):
    """
    Uses the CodeBERT model to fill the masked token in the code_str.
    """
    input_ids = tokenizer.encode(code_str, return_tensors='pt').to(device)
    mask_token_index = torch.where(input_ids == tokenizer.mask_token_id)[1]

    with torch.no_grad():
        outputs = model(input_ids)
        predictions = outputs[0]

    top_k = 10
    top_k_predictions = torch.topk(predictions[0, mask_token_index, :], top_k, dim=1).indices[0]

    res = []
    for token_id in top_k_predictions:
        predicted_token = tokenizer.decode([token_id])
        res.append(predicted_token.strip())
    return res

def test_and_validate_patches(file_path: str, start_line_1_indexed: int, end_line_1_indexed: int, test_command: str):
    """
    Generates and validates patches using a provided test command.
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
    if not masked_code:
        return

    print("--- Masked Code Snippet for model ---")
    print(masked_code)
    print("\n")

    print("--- Generating Patches with CodeBERT (This may take a moment) ---")
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
            time.sleep(0.2)
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
    parser = argparse.ArgumentParser(description="Generate and test patches for a buggy file using CodeBERT.")
    parser.add_argument("file_path", help="The path to the buggy file.")
    parser.add_argument("start_line", type=int, help="The 1-indexed starting line number of the buggy code.")
    parser.add_argument("end_line", type=int, help="The 1-indexed ending line number of the buggy code.")
    parser.add_argument("test_command", help="The base64 encoded shell command to run the test suite.")
    
    args = parser.parse_args()

    decoded_test_command = base64.b64decode(args.test_command).decode('utf-8')

    print("\nStarting patch generation and validation with CodeBERT...\n")
    test_and_validate_patches(args.file_path, args.start_line, args.end_line, decoded_test_command)
    print("\nProcess finished.")