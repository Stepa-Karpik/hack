"""Report loaded module types and stored parameter dtypes; no model outputs changed."""
def audit(model):
    result={'visual':{'linear4bit_modules':0,'parameter_dtypes':{}},
            'other':{'linear4bit_modules':0,'parameter_dtypes':{}}}
    for name,module in model.named_modules():
        group='visual' if 'visual' in name.split('.') else 'other'
        if type(module).__name__=='Linear4bit':result[group]['linear4bit_modules']+=1
    for name,param in model.named_parameters():
        group='visual' if 'visual' in name.split('.') else 'other'
        key=str(param.dtype);counts=result[group]['parameter_dtypes']
        counts[key]=counts.get(key,0)+param.numel()
    return result
