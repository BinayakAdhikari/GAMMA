import os

def generate_input_for_codebert():
    with open("inputLines_quixbugs.txt", 'r') as f:
        buggy_lines = f.readlines()

    with open("quixbugs_meta.txt", 'r') as f:
        meta_lines = f.readlines()

    written_count = 0
    with open("inputContextForCodebert.txt", 'w') as out:
        for bug in buggy_lines:
            print("[DEBUG] Processing bug line:", bug.strip())

            try:
                # Extract line number from buggy line, e.g., "line:13\tbuggy_code"
                line_no = int(bug.split('\t')[0][5:])
                buggy_code = bug.split('\t')[1].strip()
            except Exception as e:
                print(f"[ERROR] Bug line parse failed: {e}")
                continue

            if line_no >= len(meta_lines):
                print(f"[WARN] Skipping: line_no {line_no} exceeds meta lines")
                continue

            meta = meta_lines[line_no].strip()
            print("[DEBUG] Meta line:", meta)
            parts = meta.split('\t')
            if len(parts) < 3:
                print(f"[WARN] Malformed meta line: {meta}")
                continue

            bug_name = parts[0]
            bug_line = int(parts[1])
            fix_line = int(parts[2])
            print(f"[DEBUG] Bug: {bug_name}, Bug line: {bug_line}, Fix line: {fix_line}")

            java_path = os.path.join("QuixBugs", "java_programs", f"{bug_name}.java")
            if not os.path.exists(java_path):
                print(f"[WARN] Java file missing: {java_path}")
                continue

            try:
                with open(java_path, 'r') as jf:
                    code_lines = jf.readlines()

                context_radius = 5
                start = max(0, bug_line - context_radius - 1)
                end = min(len(code_lines), bug_line + context_radius)

                context_lines = code_lines[start:end]
                bug_relative_index = bug_line - 1 - start

                if 0 <= bug_relative_index < len(context_lines):
                    context_lines[bug_relative_index] = "    <mask>\n"

                context = ''.join(context_lines)

                # Write header
                out.write(f"{bug_name}\t{bug_line}\t{buggy_code}\n")
                out.write(context)
                out.write("\n---\n")
                written_count += 1


            except Exception as e:
                print(f"[ERROR] Failed processing Java file {java_path}: {e}")
                continue

    print(f"[INFO] Finished writing {written_count} bug contexts to inputContextForCodebert.txt")

if __name__ == "__main__":
    generate_input_for_codebert()
