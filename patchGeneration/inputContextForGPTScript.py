import os


def generate_input_context_for_chatgpt():
    with open("inputLines_quixbugs.txt", 'r') as f:
        buggy_lines = f.readlines()
    with open("quixbugs_meta.txt", 'r') as f:
        meta_lines = f.readlines()

    with open("inputContextForChatgpt.txt", 'w') as out:
        for bug in buggy_lines:
            line_no = int(bug.split('\t')[0][5:])
            buggy_code_line = bug.split('\t')[1].strip()
            meta = meta_lines[line_no]

            bug_name = meta.split('\t')[0]
            bug_line_start = int(meta.split('\t')[1])
            bug_line_end = int(meta.split('\t')[2])
            comment = meta.split('\t')[3].strip()

            java_file_path = os.path.join("QuixBugs", "java_programs", bug_name + ".java")

            if not os.path.exists(java_file_path):
                print(f"Missing: {java_file_path}")
                continue

            with open(java_file_path, 'r') as f:
                file_content = f.readlines()

            # Extract context within the class, skipping comments/empty lines
            context = ""
            class_found = False
            for i in range(len(file_content)):
                line = file_content[i]
                if not class_found and "public class" in line:
                    class_found = True
                    continue
                if class_found:
                    line_num = i + 1
                    if bug_line_start <= line_num <= bug_line_end:
                        continue
                    if line.strip() == "" or line.strip().startswith("//"):
                        continue
                    context += line

            # Write context with mask
            out.write(f"bugid:{bug_name}\n")
            out.write(f"line:{bug_line_start}\n")
            out.write(context.replace(buggy_code_line, buggy_code_line.replace(";", " <mask>;")) + "\n")
            out.write(f"position:1\n\n")

    print("✅ inputContextForChatgpt.txt has been generated.")

if __name__ == "__main__":
    generate_input_context_for_chatgpt()
    print("Script completed successfully.")
