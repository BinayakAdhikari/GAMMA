import sys
import os

# Add the project root to sys.path to enable imports from sibling directories
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, '..'))
sys.path.insert(0, project_root)

import torch
import csv
from patchGeneration.unixcoder import UniXcoder
from transformers import RobertaConfig, RobertaTokenizer, RobertaForMaskedLM, pipeline

# --- Model Initialization ---
# UniXcoder
unixcoder_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
unixcoder_model = UniXcoder("microsoft/unixcoder-base")
unixcoder_model.to(unixcoder_device)

# CodeBERT
codebert_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
codebert_tokenizer = RobertaTokenizer.from_pretrained("microsoft/codebert-base-mlm")
codebert_model = RobertaForMaskedLM.from_pretrained("microsoft/codebert-base-mlm")
codebert_model.to(codebert_device)
codebert_fill_mask_pipeline = pipeline('fill-mask', model=codebert_model, tokenizer=codebert_tokenizer, device=0 if torch.cuda.is_available() else -1)

# --- Helper Functions ---
def insert_mask_token(code: str, buggy_line_num: int, mask_token: str, context_before: int = 2, context_after: int = 2) -> str:
    """
    Extracts a context window around the buggy line and inserts mask_token in place of the buggy line.
    buggy_line_num is 0-indexed.
    """
    lines = code.splitlines()
    total_lines = len(lines)

    if not (0 <= buggy_line_num < total_lines):
        return code

    start_index = max(0, buggy_line_num - context_before)
    end_index = min(total_lines - 1, buggy_line_num + context_after)

    context_lines = lines[start_index : end_index + 1]
    
    # Calculate the new 0-indexed position of the buggy line within the context_lines list
    buggy_line_in_context = buggy_line_num - start_index
    
    context_lines[buggy_line_in_context] = mask_token
    
    return "\n".join(context_lines)

def unixcoder_fill_mask(code_str, target_line_placeholder="<mask0>"):
    tokens_ids = unixcoder_model.tokenize([code_str], max_length=512, mode="<encoder-decoder>")
    source_ids = torch.tensor(tokens_ids).to(unixcoder_device)
    prediction_ids = unixcoder_model.generate(source_ids, decoder_only=False, beam_size=25, max_length=128)
    predictions = unixcoder_model.decode(prediction_ids)
    
    res = []
    for prediction in predictions[0]:
        patched_line = prediction.replace(target_line_placeholder, '')
        res.append(patched_line.strip())
    return res

def codebert_fill_mask(code_str, original_code_lines, buggy_line_0_indexed, target_line_placeholder="<mask>", top_k=25):
    results = codebert_fill_mask_pipeline(code_str, top_k=top_k)
    
    res = []
    for r in results:
        filled_sequence_lines = r['sequence'].splitlines()
        
        if len(filled_sequence_lines) > buggy_line_0_indexed:
            predicted_line = filled_sequence_lines[buggy_line_0_indexed]
            res.append(predicted_line.strip())
        else:
            res.append(r['sequence'].strip()) # Fallback
    return res

def parse_defects4j_summary(summary_file_path):
    fixed = []
    plausible = []
    unfixed = []
    current_section = None

    try:
        with open(summary_file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("fixed:"):
                    current_section = fixed
                elif line.startswith("plausible:"):
                    current_section = plausible
                elif line.startswith("unfixed:"):
                    current_section = unfixed
                elif line.startswith("total:"):
                    pass # Ignore total lines for now
                elif current_section is not None and line:
                    current_section.append(line.split(':')[0].strip()) # Get project name
    except FileNotFoundError:
        print(f"Warning: Defects4J summary file not found at {summary_file_path}")
    
    return {
        "fixed": fixed,
        "plausible": plausible,
        "unfixed": unfixed
    }

# --- Main Comparison Logic ---
def compare_models_on_quixbugs(
    meta_path=r"E:\Marburg Uni\Third Semester\GAMMA Seminar\GAMMA\patchGeneration\quixbugs_meta.txt",
    input_lines_path=r"E:\Marburg Uni\Third Semester\GAMMA Seminar\GAMMA\patchGeneration\inputLines_quixbugs.txt",
    defects4j_summary_path=r"E:\Marburg Uni\Third Semester\GAMMA Seminar\GAMMA\results\unixcoder_results\summary.txt",
    num_quixbugs_snippets=20,
    output_report_path=r"E:\Marburg Uni\Third Semester\GAMMA Seminar\GAMMA\test_output\model_patching_comparison_report.md",
    output_csv_path=r"E:\Marburg Uni\Third Semester\GAMMA Seminar\GAMMA\test_output\patching_comparison_data.csv"
):
    report_content = []
    csv_data = []

    report_content.append("# UniXcoder vs. CodeBERT Patching Comparison (QuixBugs)\n")
    report_content.append("This report compares the patch generation capabilities of UniXcoder and CodeBERT models on a subset of the QuixBugs dataset.\n\n")
    report_content.append("**Note:** This report only indicates whether a patch was *generated* by the model. It does not assess the *correctness* of the patch, as that requires a testing framework.\n\n")

    # --- QuixBugs Data Collection ---
    buggy_programs_meta = []
    try:
        with open(meta_path, "r") as f_meta:
            for line in f_meta:
                parts = line.strip().split('\t')
                if len(parts) >= 4:
                    buggy_programs_meta.append((parts[0], int(parts[2]), parts[3])) # (name, 1-indexed line, desc)
    except FileNotFoundError:
        report_content.append(f"Error: QuixBugs metadata file not found at {meta_path}\n\n")
        return "".join(report_content)

    buggy_snippets_raw = []
    try:
        with open(input_lines_path, "r") as f_input:
            buggy_snippets_raw = f_input.readlines()
    except FileNotFoundError:
        report_content.append(f"Error: Input buggy lines file not found at {input_lines_path}\n\n")
        return "".join(report_content)

    total_processed_quixbugs = 0
    unixcoder_patched_count_quixbugs = 0
    codebert_patched_count_quixbugs = 0

    # CSV Header for QuixBugs
    csv_data.append(["Dataset", "ProgramName", "BuggyLine", "Model", "PatchesGenerated"])

    for i in range(min(num_quixbugs_snippets, len(buggy_programs_meta))):
        program_name, buggy_line_1_indexed, bug_description = buggy_programs_meta[i]
        original_snippet = buggy_snippets_raw[i].strip()
        buggy_line_0_indexed = buggy_line_1_indexed - 1

        report_content.append(f"## {i+1}. Program: {program_name} (Buggy Line: {buggy_line_1_indexed})\n")
        report_content.append(f"**Bug Description:** {bug_description}\n\n")
        report_content.append("### Original Code Snippet\n")
        report_content.append("```python\n") # Assuming Python for display, adjust if needed
        lines = original_snippet.splitlines()
        for idx, line in enumerate(lines):
            if idx == buggy_line_0_indexed:
                report_content.append(f">> {line}\n")
            else:
                report_content.append(f"   {line}\n")
        report_content.append("```\n\n")

        # --- UniXcoder Patching ---
        report_content.append("### UniXcoder Patches\n")
        unixcoder_masked_code = insert_mask_token(original_snippet, buggy_line_0_indexed, "<mask0>")
        report_content.append("**Masked Code for UniXcoder:**\n")
        report_content.append("```python\n")
        report_content.append(unixcoder_masked_code + "\n")
        report_content.append("```\n")
        try:
            unixcoder_patches = unixcoder_fill_mask(unixcoder_masked_code)
            if unixcoder_patches:
                unixcoder_patched_count_quixbugs += 1
                report_content.append("**Generated Patches (Top 5):**\n")
                report_content.append("```python\n")
                for idx, patch in enumerate(unixcoder_patches[:5]):
                    report_content.append(f"- {patch}\n")
                report_content.append("```\n")
                csv_data.append(["QuixBugs", program_name, buggy_line_1_indexed, "UniXcoder", 1])
            else:
                report_content.append("**No patches generated by UniXcoder.**\n")
                csv_data.append(["QuixBugs", program_name, buggy_line_1_indexed, "UniXcoder", 0])
        except Exception as e:
            report_content.append(f"**Error during UniXcoder patching:** {e}\n")
            csv_data.append(["QuixBugs", program_name, buggy_line_1_indexed, "UniXcoder", 0])
        report_content.append("\n")

        # --- CodeBERT Patching ---
        report_content.append("### CodeBERT Patches\n")
        codebert_masked_code = insert_mask_token(original_snippet, buggy_line_0_indexed, "<mask>")
        report_content.append("**Masked Code for CodeBERT:**\n")
        report_content.append("```python\n")
        report_content.append(codebert_masked_code + "\n")
        report_content.append("```\n")
        try:
            codebert_patches = codebert_fill_mask(codebert_masked_code, lines, buggy_line_0_indexed)
            if codebert_patches:
                codebert_patched_count_quixbugs += 1
                report_content.append("**Generated Patches (Top 5):**\n")
                report_content.append("```python\n")
                for idx, patch in enumerate(codebert_patches[:5]):
                    report_content.append(f"- {patch}\n")
                report_content.append("```\n")
                csv_data.append(["QuixBugs", program_name, buggy_line_1_indexed, "CodeBERT", 1])
            else:
                report_content.append("**No patches generated by CodeBERT.**\n")
                csv_data.append(["QuixBugs", program_name, buggy_line_1_indexed, "CodeBERT", 0])
        except Exception as e:
            report_content.append(f"**Error during CodeBERT patching:** {e}\n")
            csv_data.append(["QuixBugs", program_name, buggy_line_1_indexed, "CodeBERT", 0])
        report_content.append("\n")
        total_processed_quixbugs += 1

    report_content.append("## Summary (QuixBugs)\n")
    report_content.append(f"Total QuixBugs snippets processed: {total_processed_quixbugs}\n")
    report_content.append(f"UniXcoder generated patches for: {unixcoder_patched_count_quixbugs} snippets\n")
    report_content.append(f"CodeBERT generated patches for: {codebert_patched_count_quixbugs} snippets\n")

    # --- Defects4J Summary Data (from pre-existing file) ---
    defects4j_summary = parse_defects4j_summary(defects4j_summary_path)
    report_content.append("\n## Defects4J Summary (UniXcoder - from existing summary file)\n")
    report_content.append("This data is extracted from `results/unixcoder_results/summary.txt` and represents pre-computed results, not live patching.\n\n")
    
    # CSV Header for Defects4J Summary
    csv_data.append(["Dataset", "Project", "Model", "Fixed", "Plausible", "Unfixed"])

    # Collect all unique project names from fixed, plausible, unfixed lists
    all_defects4j_projects = sorted(list(set(
        defects4j_summary["fixed"] +
        defects4j_summary["plausible"] +
        defects4j_summary["unfixed"]
    )))

    for project in all_defects4j_projects:
        is_fixed = 1 if project in defects4j_summary["fixed"] else 0
        is_plausible = 1 if project in defects4j_summary["plausible"] else 0
        is_unfixed = 1 if project in defects4j_summary["unfixed"] else 0
        
        report_content.append(f"- **{project}**: Fixed: {is_fixed}, Plausible: {is_plausible}, Unfixed: {is_unfixed}\n")
        csv_data.append(["Defects4J", project, "UniXcoder", is_fixed, is_plausible, is_unfixed])
        # Add placeholder for CodeBERT Defects4J if no data is available
        csv_data.append(["Defects4J", project, "CodeBERT", "N/A", "N/A", "N/A"])

    # Write Markdown Report
    with open(output_report_path, "w") as f_out:
        f_out.writelines(report_content)
    print(f"Comparison report generated successfully at: {output_report_path}")

    # Write CSV Data
    with open(output_csv_path, 'w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        csv_writer.writerows(csv_data)
    print(f"Comparison CSV data generated successfully at: {output_csv_path}")

if __name__ == "__main__":
    compare_models_on_quixbugs()