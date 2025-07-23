import torch
from patchGeneration.unixcoder import UniXcoder
import os
import random
import argparse
import subprocess
import time

# Initialize UniXcoder model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = UniXcoder("microsoft/unixcoder-base")
model.to(device)

def get_random_buggy_file(java_programs_dir: str, quixbugs_meta_path: str):
    """
    Selects a random Java file that has corresponding metadata.
    """
    print(f"Searching for metadata in: {quixbugs_meta_path}")
    programs_with_meta = {}
    try:
        with open(quixbugs_meta_path, "r") as f_meta:
            for line in f_meta:
                try:
                    parts = line.strip().split('	')
                    program_name = parts[0]
                    start_line = int(parts[1])
                    end_line = int(parts[2])
                    programs_with_meta[program_name] = (start_line, end_line)
                except (IndexError, ValueError):
                    continue # Skip malformed lines
    except FileNotFoundError:
        print(f"Error: Metadata file not found at {quixbugs_meta_path}")
        return None, None, None, None

    print(f"Found metadata for {len(programs_with_meta)} programs.")

    # Find which of the programs with metadata actually exist as files
    available_programs = [
        p for p in programs_with_meta.keys() 
        if os.path.exists(os.path.join(java_programs_dir, f"{p}.java"))
    ]
    
    print(f"Found {len(available_programs)} matching Java files in {java_programs_dir}.")
    if not available_programs:
        return None, None, None, None

    random_program_name = random.choice(available_programs)
    file_path = os.path.join(java_programs_dir, f"{random_program_name}.java")
    start_line, end_line = programs_with_meta[random_program_name]
    
    return file_path, random_program_name, start_line, end_line

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

    masked_code_list = pre_context + ["<mask0>"] + post_context
    
    return "\n".join(masked_code_list)

def generate_patch_unixcoder(masked_code: str):
    """
    Uses the UniXcoder model to generate patches.
    """
    tokens_ids = model.tokenize([masked_code], max_length=512, mode="<encoder-decoder>")
    source_ids = torch.tensor(tokens_ids).to(device)
    prediction_ids = model.generate(source_ids, decoder_only=False, beam_size=25, max_length=128)
    predictions = model.decode(prediction_ids)
    
    res = []
    for prediction in predictions[0]:
        patched_line = prediction.replace("<mask0>", '').strip()
        if patched_line:
            res.append(patched_line)
    return res

def test_and_validate_patches(file_path: str, start_line_1_indexed: int, end_line_1_indexed: int, test_command: str, program_name: str):
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

    print("--- Generating Patches with UniXcoder (This may take a moment) ---")
    try:
        patches = generate_patch_unixcoder(masked_code)
        if not patches:
            print("No patches generated.")
            return

        print(f"--- Generated {len(patches)} Patches. Now validating... ---")

        lines = original_code.splitlines()
        validated_patches = 0
        
        # Setup directory for saving patches
        patches_output_dir = os.path.join("generated_patches", program_name)
        os.makedirs(patches_output_dir, exist_ok=True)

        original_file_backup_path = f"{file_path}.bak"
        if os.path.exists(original_file_backup_path):
            os.remove(original_file_backup_path)
            
        os.rename(file_path, original_file_backup_path)
        
        try:
            for idx, patch in enumerate(patches):
                # Save the patch to a file
                patch_filename = os.path.join(patches_output_dir, f"patch_{idx + 1:02d}.txt")
                with open(patch_filename, 'w') as f_patch:
                    f_patch.write(patch)
                print(f"Saved patch to: {patch_filename}")

                print(f"--- Testing Patch {idx + 1}:\n{patch}\n---")

                patched_lines = lines[:start_line_0] + patch.splitlines() + lines[end_line_0 + 1:]
                full_patched_code = '\n'.join(patched_lines)
                with open(file_path, 'w') as f:
                    f.write(full_patched_code)

                # print("--- Full Patched Program (for testing) ---")
                # print(full_patched_code)
                # print("--------------------------------------------")

                # Compile the patched Java file using javac
                QUIXBUGS_DIR = "patchGeneration/QuixBugs"
                relative_file_path = os.path.relpath(file_path, QUIXBUGS_DIR)
                compile_command = f"cd {QUIXBUGS_DIR} && javac {relative_file_path}"
                compile_result = subprocess.run(compile_command, shell=True, capture_output=True, text=True)

                if compile_result.returncode != 0:
                    print(f"COMPILATION FAILED: Patch {idx + 1} failed to compile.")
                    print("--- JAVAC Output ---")
                    print(compile_result.stdout)
                    print(compile_result.stderr)
                    continue # Skip testing if compilation fails

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
        if 'original_file_backup_path' in locals() and os.path.exists(original_file_backup_path):
            os.replace(original_file_backup_path, file_path)

def main():
    parser = argparse.ArgumentParser(description="Randomly select a buggy Java file from QuixBugs, generate a patch using UniXcoder, and test it.")
    parser.add_argument("--meta_file", default="patchGeneration/quixbugs_meta.txt", help="Path to the quixbugs_meta.txt file.")
    args = parser.parse_args()

    QUIXBUGS_DIR = "patchGeneration/QuixBugs"
    JAVA_PROGRAMS_DIR = os.path.join(QUIXBUGS_DIR, "java_programs")

    file_path, prog_name, start_line, end_line = get_random_buggy_file(JAVA_PROGRAMS_DIR, args.meta_file)

    if not file_path:
        print("Could not find a buggy file or metadata. Exiting.")
    else:
        print(f"--- Selected Buggy Program: {prog_name} ---")
        test_class_name = f"{prog_name}_TEST"
        test_command = f"cd {QUIXBUGS_DIR} && gradle test --tests {test_class_name}"
        
        print(f"Using test command: {test_command}\n")
        test_and_validate_patches(file_path, start_line, end_line, test_command, prog_name)

    print("\nProcess finished.")

if __name__ == "__main__":
    main()