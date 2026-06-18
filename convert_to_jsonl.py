import json
import argparse
import sys

def convert_to_jsonl(original_file, translation_file, output_file):
    """
    한자 원문 파일과 해석본 파일을 읽어서 JSONL 형식으로 변환합니다.
    """
    try:
        with open(original_file, 'r', encoding='utf-8') as f_orig, \
             open(translation_file, 'r', encoding='utf-8') as f_trans, \
             open(output_file, 'w', encoding='utf-8') as f_out:
            
            # 모든 줄을 읽어옵니다
            orig_lines = f_orig.readlines()
            trans_lines = f_trans.readlines()
            
            # 빈 줄을 제거하고 양쪽 공백을 제거합니다
            orig_lines = [line.strip() for line in orig_lines if line.strip()]
            trans_lines = [line.strip() for line in trans_lines if line.strip()]
            
            # 줄 수가 다를 경우 경고 메시지를 출력합니다
            if len(orig_lines) != len(trans_lines):
                print(f"경고: 두 파일의 줄 수가 다릅니다! 원문: {len(orig_lines)}줄, 해석: {len(trans_lines)}줄")
            
            # 더 적은 줄 수에 맞춰서 변환합니다
            max_len = min(len(orig_lines), len(trans_lines))
            
            for i in range(max_len):
                data = {
                    "original": orig_lines[i],
                    "translation": trans_lines[i]
                }
                # json.dumps를 사용하여 딕셔너리를 JSON 문자열로 변환 후 저장 (ensure_ascii=False로 한글 깨짐 방지)
                f_out.write(json.dumps(data, ensure_ascii=False) + '\n')
                
        print(f"성공적으로 {max_len}개의 문장을 {output_file} 파일로 변환했습니다.")
            
    except FileNotFoundError as e:
        print(f"파일을 찾을 수 없습니다: {e.filename}")
    except Exception as e:
        print(f"오류가 발생했습니다: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="한자 원문과 해석본을 JSONL 파일로 변환합니다.")
    parser.add_argument("--orig", required=True, help="한자 원문 텍스트 파일 경로")
    parser.add_argument("--trans", required=True, help="해석본 텍스트 파일 경로")
    parser.add_argument("--out", default="output.jsonl", help="출력될 JSONL 파일 경로 (기본값: output.jsonl)")
    
    args = parser.parse_args()
    
    convert_to_jsonl(args.orig, args.trans, args.out)