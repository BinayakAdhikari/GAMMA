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



def fillMask(code, maskNum):
    res=[]

    if maskNum==1:
        outputs=fill_mask(code)

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
                tempOutputs=fill_mask(output['sequence'][3:-4])[0]
            else:
                tempOutputs=fill_mask(output['sequence'][3:-4])
            for o in tempOutputs:
                o['tempJointScore']=(output['tempJointScore']*i+math.log(o['score']))/(i+1)
            newOutputs.extend(tempOutputs)
        newOutputs.sort(key=lambda k: (k.get('tempJointScore', 0)), reverse=True)
        outputs=newOutputs

    for i in range(0,250):
#        print(outputs[i])
        res.append(outputs[i])
    return res


def read_file_and_fill_mask():
    with open("inputContextForCodebert.txt", 'r') as f:
        content = f.read()

    blocks = content.strip().split("\n---\n")

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue

        header = lines[0].strip()
        print(f"[DEBUG] Header: '{header}'")  # 👈 Add this line

        parts = header.split('\t')
        if len(parts) != 3:
            print(f"[WARN] Skipping malformed header: '{header}'")
            continue

        bug_name, bug_line_str, buggy_code = parts
        bug_line = int(bug_line_str)

        code_lines = lines[1:]
        if '<mask>' not in '\n'.join(code_lines):
            continue

        # Find which line has the <mask>
        target_line_no = -1
        for idx, l in enumerate(code_lines):
            if '<mask>' in l:
                target_line_no = idx
                break

        if target_line_no == -1:
            print(f"[WARN] No mask found in bug: {bug_name}")
            continue

        context = '\n'.join(code_lines)
        mask_num = context.count("<mask>")

        try:
            res = fillMask(context, mask_num)
            print(f"\n==== Predictions for {bug_name}, buggy line {bug_line} ====")
            for idx, output in enumerate(res[:5]):
                sequence = output['sequence']
                sequence_lines = sequence.split('\n')
                if target_line_no < len(sequence_lines):
                    print(f"Suggestion {idx+1}: {sequence_lines[target_line_no]}")
                    print(f"Score: {output['score']:.5f}")
                else:
                    print(f"[WARN] Output too short for line {target_line_no}")
        except Exception as e:
            print(f"[ERROR] Failed on {bug_name}: {e}")


if __name__=='__main__':
    read_file_and_fill_mask()
