#!/usr/bin/env python3
"""Compare local command backends on identical choice requests without publishing request bodies."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
import yaml
from tools.choice_answerer import check_observations
from tools.element import canonical
from tools.element_answerer import LocalAnswerer, StableChoiceAnswerer, request_kind


def compare(requests, llm, judge):
    if not isinstance(requests,list) or not requests or len(requests)>100:
        raise ValueError('Use between one and 100 permitted choice requests')
    totals={name:{'pairs':0,'stable':0,'errors':0,'seconds':0,'costs':[], 'positions':Counter()} for name in ['llm','judge']}
    rows=[]; agreement=0; comparable=0
    for req in requests:
        if request_kind(req)!='element' or req['answer_format']['type']!='choice':
            raise ValueError('Comparison only accepts choice requests')
        row={'request_sha256':hashlib.sha256(canonical(req).encode()).hexdigest(),'backends':{}}
        values={}
        for name,backend in [('llm',llm),('judge',judge)]:
            total=totals[name];total['pairs']+=1
            try:
                reply=StableChoiceAnswerer(backend, 'judge-benchmark').answer(req)
                stable=not check_observations(req,reply)
                total['stable']+=int(stable);values[name]=reply['value']
                observations=reply['choice_observations']
                for obs in observations:
                    # Display position is computed from what the worker actually saw.
                    from tools.choice_answerer import presentation
                    shown=presentation(req,obs['order'])['answer_format']['choices']
                    total['positions'][str(shown.index(obs['value'])+1)]+=1
                    total['seconds']+=obs['elapsed_seconds'];total['costs'].append(obs['cost_usd'])
                row['backends'][name]={'stable':stable,'seconds':sum(o['elapsed_seconds'] for o in observations),
                                       'cost_usd':None if any(o['cost_usd'] is None for o in observations) else sum(o['cost_usd'] for o in observations)}
            except (ValueError,OSError,KeyError,TypeError) as exc:
                total['errors']+=1;row['backends'][name]={'status':'ERROR','error_type':type(exc).__name__}
        if len(values)==2:
            comparable+=1;agreement+=int(values['llm']==values['judge'])
            row['same_original_choice']=values['llm']==values['judge']
        rows.append(row)
    summary={}
    for name,total in totals.items():
        costs=total.pop('costs');total['cost_usd']=None if total['errors'] or not costs or any(c is None for c in costs) else sum(costs)
        total['position_counts']=dict(sorted(total.pop('positions').items()))
        total['seconds_scope']='all_pairs' if not total['errors'] else 'completed_pairs_only'
        total['stability_rate']=total['stable']/total['pairs']
        summary[name]=total
    # This measures consistency and agreement, not a ground-truth accuracy claim.
    return {'contract_version':'element-comparison/v1','sample_count':len(requests),'comparable_count':comparable,
            'choice_agreement_rate':agreement/comparable if comparable else None,'backends':summary,
            'rows':rows,'decision':'KEEP_LLM_DEFAULT','reason':'Bounded comparison is not owner-run accuracy acceptance.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests',type=Path,required=True)
    parser.add_argument('--llm-config',type=Path,required=True)
    parser.add_argument('--judge-config',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        report=compare(json.loads(args.requests.read_text()),
                       LocalAnswerer(yaml.safe_load(args.llm_config.read_text())),
                       LocalAnswerer(yaml.safe_load(args.judge_config.read_text())))
        print(canonical(report),end='');return 0
    except (ValueError,OSError,yaml.YAMLError):
        print('Invalid comparison configuration or request input',file=sys.stderr);return 1

if __name__=='__main__': raise SystemExit(main())
