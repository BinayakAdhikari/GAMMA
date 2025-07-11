import torch
from unixcoder import UniXcoder
import os

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = UniXcoder("microsoft/unixcoder-base")
model.to(device)

def insert_mask_token(code: str, buggy_line_num: int) -> str:
    """
    Insert <mask0> in place of the line at buggy_line_num.
    """
    lines = code.splitlines()
    if 0 <= buggy_line_num < len(lines):
        print(f"Inserting <mask0> at line {buggy_line_num}: {lines[buggy_line_num]}")
        lines[buggy_line_num] = "<mask0>"
        return "\n".join(lines)
    else:
        print(f"Warning: Invalid line number {buggy_line_num}. No masking applied.")
        return code

def fill_mask(code_str, buggy_line, target_line):
    prompt = f"""The following Java code is buggy:\n\n{code_str}\n\nThe bug is in the following line:\n\n{buggy_line}\n\nPlease provide a corrected version of this line.\n"""
    tokens_ids = model.tokenize([prompt], max_length=512, mode="<encoder-decoder>")
    source_ids = torch.tensor(tokens_ids).to(device)
    prediction_ids = model.generate(source_ids, decoder_only=False, beam_size=10, max_length=128)
    predictions = model.decode(prediction_ids)
    res = []
    for prediction in predictions[0]:
        tmp = target_line.replace('<mask0>', prediction.replace('<mask0>', '')).split('\n')
        output = ''
        for line in tmp:
            output += line
            output += ' '
        res.append(output.strip())
    return res

def repair_from_quixbugs(input_path="patchGeneration/inputLines_quixbugs.txt", meta_path="patchGeneration/quixbugs_meta.txt", results_dir="patchGeneration/unixcoder_patches/"):
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)

    with open(input_path, "r") as f_in, open(meta_path, "r") as f_meta:
        buggy_code = f_in.read()
        meta_lines = f_meta.readlines()

    buggy_snippets = buggy_code.split("package java_programs;")
    if buggy_snippets[0].strip() == "":
        buggy_snippets.pop(0)

    total_bugs = len(buggy_snippets)
    masked_count = 0
    patched_count = 0

    print(f"Total buggy snippets: {total_bugs}")
    for i, buggy_snippet in enumerate(buggy_snippets):
        buggy_snippet = "package java_programs;" + buggy_snippet
        print(f"\nProcessing snippet {i+1}/{total_bugs}...")

        tokens = meta_lines[i].split()
        try:
            line_no = int(tokens[2])  # 3rd column is the buggy line number
        except (IndexError, ValueError):
            print(f"Invalid metadata format at line {i+1}, skipping...")
            continue

        masked_code = insert_mask_token(buggy_snippet, line_no - 1)
        masked_count += 1

        try:
            patches = fill_mask(masked_code, buggy_snippet.splitlines()[line_no - 1], "<mask0>")
            if patches:
                patched_count += 1
                output_path = os.path.join(results_dir, f"{i+1:03d}_line{line_no}.txt")
                with open(output_path, "w") as f_out:
                    for patch in patches:
                        f_out.write(patch + "\n")

                print("Top 5 fixes:")
                for idx, patch in enumerate(patches[:5]):
                    print(f"Fix {idx + 1}: {patch}")
            else:
                print(f"No patches generated for snippet {i+1}.")
        except Exception as e:
            print(f"Error repairing snippet {i+1} at line {line_no}: {e}")

    print("\n====== Summary ======")
    print(f"Total buggy snippets: {total_bugs}")
    print(f"Masked correctly     : {masked_count}")
    print(f"Successfully patched : {patched_count}")
    print(f"Check folder: {results_dir}")

if __name__ == "__main__":
    repair_from_quixbugs()
