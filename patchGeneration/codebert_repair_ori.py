import os
from transformers import RobertaConfig,RobertaTokenizer,RobertaForMaskedLM,pipeline
import math
import torch

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = RobertaForMaskedLM.from_pretrained("microsoft/codebert-base-mlm")
tokenizer = RobertaTokenizer.from_pretrained("microsoft/codebert-base-mlm")
model.to(device)

fill_mask = pipeline('fill-mask',
                     model=model,
                     tokenizer=tokenizer)
# fill_mask.device = torch.device("cuda:0")



def fillMask(code, buggy_line, maskNum):
    prompt = f"""The following Java code is buggy:\n\n{code}\n\nThe bug is in the following line:\n\n{buggy_line}\n\nPlease provide a corrected version of this line.\n"""
    res=[]

    if maskNum==1:
        outputs=fill_mask(prompt, top_k=10)
        print(f"Raw outputs from fill_mask: {outputs}")

        for output in outputs:
            res.append(output)
#            print(output)
        return res


    outputs=fill_mask(code)[0]
    for output in outputs:
        output['tempJointScore']=math.log(output['score'])

    for i in range(1,maskNum):
        newOutputs=[]
        for j in range(0,250):
            output=outputs[j]
            if i!=maskNum-1:
                tempOutputs=fill_mask(output['sequence'][3:-4], top_k=50)[0]
            else:
                tempOutputs=fill_mask(output['sequence'][3:-4], top_k=50)
            for o in tempOutputs:
                o['tempJointScore']=(output['tempJointScore']*i+math.log(o['score']))/(i+1)
            newOutputs.extend(tempOutputs)
        newOutputs.sort(key=lambda k: (k.get('tempJointScore', 0)), reverse=True)
        outputs=newOutputs

    for i in range(0,250):
#        print(outputs[i])
        res.append(outputs[i])
    return res


def repair_from_quixbugs(input_path="patchGeneration/inputLines_quixbugs.txt", meta_path="patchGeneration/quixbugs_meta.txt", results_dir="patchGeneration/codebert_patches/"):
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
            line_no = int(tokens[2])
        except (IndexError, ValueError):
            print(f"Invalid metadata format at line {i+1}, skipping...")
            continue

        original_lines = buggy_snippet.splitlines()
        if 0 <= line_no - 1 < len(original_lines):
            masked_lines = list(original_lines) # Create a mutable copy
            masked_lines[line_no - 1] = "<mask>"
            masked_code = "\n".join(masked_lines)
            masked_count += 1
        else:
            print(f"Warning: Invalid line number {line_no}. No masking applied.")
            masked_code = buggy_snippet

        # Truncate the input to the model
        tokenized_input = tokenizer.tokenize(masked_code)
        if len(tokenized_input) > 510:
            tokenized_input = tokenized_input[:510]
        masked_code = tokenizer.convert_tokens_to_string(tokenized_input)

        try:
            patches = fillMask(masked_code, original_lines[line_no - 1], 1)
            if patches:
                patched_count += 1
                output_path = os.path.join(results_dir, f"{i+1:03d}_line{line_no}.txt")
                with open(output_path, "w") as f_out:
                    for patch in patches:
                        # Extract only the patched line
                        patched_sequence_lines = patch['sequence'].splitlines()
                        if 0 <= line_no - 1 < len(patched_sequence_lines):
                            patched_line = patched_sequence_lines[line_no - 1].strip()
                            f_out.write(patched_line + "\n")
                        else:
                            print(f"Warning: Patched sequence too short for bug {bugName}. Writing full sequence.")
                            f_out.write(patch['sequence'] + "\n")

                print("Top 5 fixes:")
                for idx, patch in enumerate(patches[:5]):
                    patched_sequence_lines = patch['sequence'].splitlines()
                    if 0 <= line_no - 1 < len(patched_sequence_lines):
                        print(f"Fix {idx + 1}: {patched_sequence_lines[line_no - 1].strip()}")
                    else:
                        print(f"Fix {idx + 1}: (Full sequence) {patch['sequence']}")
            else:
                print(f"No patches generated for snippet {i+1}.")
        except Exception as e:
            print(f"Error repairing snippet {i+1} at line {line_no}: {e}")

    print("\n====== Summary ======")
    print(f"Total buggy snippets: {total_bugs}")
    print(f"Masked correctly     : {masked_count}")
    print(f"Successfully patched : {patched_count}")
    print(f"Check folder: {results_dir}")

if __name__=='__main__':
    repair_from_quixbugs()
