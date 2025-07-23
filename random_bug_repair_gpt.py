import torch
from transformers import GPT2LMHeadModel, GPT2Tokenizer
import os
import random
import argparse
import subprocess
import time

# Initialize GPT-2 model
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
tokenizer = GPT2Tokenizer.from_pretrained("gpt2")
model = GPT2LMHeadModel.from_pretrained("gpt2")
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
                    parts = line.strip().split('\t')
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

def create_prompt(code: str, start_line: int, end_line: int):
    """
    Creates a detailed prompt for the GPT model to generate a fix.
    """
    lines = code.splitlines()
    buggy_lines = "\n".join(lines[start_line:end_line+1])

    prompt = f"""Given the following Java code with a bug in lines {start_line + 1} to {end_line + 1}:

```java
{code}
```

The buggy snippet is:

```java
{buggy_lines}
```

Provide ONLY the corrected Java code for the buggy snippet. Do not include any explanations or surrounding code. Start directly with the code.

```java
"""
    return prompt

def generate_patch_gpt(prompt: str):
    """
    Uses the GPT-2 model to generate a patch from a prompt.
    """
    tokenizer.pad_token = tokenizer.eos_token # Set pad token to eos token
    input_ids = tokenizer.encode(prompt, return_tensors='pt').to(device)
    
    # Generate a sequence of tokens
    output_sequences = model.generate(
        input_ids=input_ids,
        attention_mask=input_ids.ne(tokenizer.pad_token_id), # Create attention mask
        max_length=len(input_ids[0]) + 60, # Allow for a reasonable patch length
        num_return_sequences=5, # Generate a few candidates
        do_sample=True,
        top_k=50,
        top_p=0.95,
        temperature=0.8,
        pad_token_id=tokenizer.eos_token_id
    )

    patches = []
    for generated_sequence in output_sequences:
        # Decode the generated sequence and extract the new code
        text = tokenizer.decode(generated_sequence, skip_special_tokens=True)
        # Extract the code generated after the prompt
        patch_text = text[len(prompt):].strip()
        # Look for the closing ``` to extract the code
        if "```" in patch_text:
            patch_text = patch_text.split("```")[0].strip()
        
        # A simple heuristic to clean up the patch
        if "\n\n" in patch_text:
            patch_text = patch_text.split("\n\n")[0]
        patches.append(patch_text)
    return patches

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

    prompt = create_prompt(original_code, start_line_0, end_line_0)
    
    print("--- Generating Patches with GPT-2 (This may take a moment) ---")
    try:
        patches = generate_patch_gpt(prompt)
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
        if 'original_file_backup_path' in locals() and os.path.exists(original_file_backup_path):
            os.replace(original_file_backup_path, file_path)

def main():
    parser = argparse.ArgumentParser(description="Randomly select a buggy Java file from QuixBugs, generate a patch using GPT-2, and test it.")
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
