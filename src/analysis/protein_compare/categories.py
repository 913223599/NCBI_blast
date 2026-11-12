# -*- coding: utf-8 -*-
"""
核心功能蛋白分类词典与结构域命名规则模块 (Categories & Domain Naming Rules)
职责：
1. 定义蛋白质生物学功能大类及其正则匹配/排除模式；
2. 依据功能大类与产品描述动态推导 N-端、中段、C-端结构域名称。
"""
from typing import Dict, Any, Tuple

PROTEIN_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "tail_fiber": {
        "label": "尾丝与宿主识别系统 (Tail Fiber & Host Specificity)",
        "patterns": [
            r"\btail\b",
            r"\btail[- ]?(?:fibers?|fibres?|spikes?|tubes?|sheaths?|shafts?|tips?|assembly|proteins?|hydrolases?|chaperones?|lysozymes?|collar|completion)\b",
            r"\btailspikes?\b",
            r"\bbaseplates?\b",
            r"\btape[- ]?measure\b",
            r"\btmp\b",
            r"\btpm\b",
            r"\breceptor[- ]?(?:binding|recogni(?:tion|zing))\b",
            r"\brbp\b",
            r"\bhost[- ]?(?:specificity|range|recognition)\b",
            r"\badhesins?\b",
            r"\bcollar\b",
            r"\bwhiskers?\b",
            r"\b(?:distal|proximal|hinge)\s+connectors?\b",
            r"\bneck\s+(?:proteins?|passage|appendages?)\b",
            r"\bhead[- ]to[- ]tail\b",
            r"\badaptor\s+ad4\b",
            r"\bwedge\b",
            r"\bcentral\s+hub\b",
            r"\bspike\s+(?:proteins?|tips?|g\b)\b",
            r"\bdepolymerases?\b",
            r"\b(?:endo[- ]?)?sialidases?\b",
            r"\bneuraminidases?\b",
            r"\bhyaluronidases?\b",
            r"\bpectin\s+lyases?\b",
            r"\bcolanic\s+acid\b",
        ],
        "exclude": [
            r"\bhead[- ]?fibers?\b",
        ]
    },
    "lysis": {
        "label": "裂解系统与溶菌酶 (Lysis / Endolysin / Spanin / Holin)",
        "patterns": [
            r"\bendolysins?\b",
            r"\b[a-z0-9'-]*lysins?\b",
            r"\blysozymes?\b",
            r"\b(?:anti[- ]?)?holins?\b",
            r"\b(?:i-|o-|u-|peri(?:plasmic)?[- ]|outer[- ]membrane[- ]|inner[- ]membrane[- ]|unimolecular[- ])?spanins?\b",
            r"\bpeptidoglycan\s+(?:hydrolases?|recognition|catabolic|binding|endopeptidases?|lytic)\b",
            r"\b[a-z0-9'-]*muramidases?\b",
            r"\b(?:soluble\s+)?lytic\s+(?:murein\s+)?transglycosylases?\b",
            r"\btransglycosylases?\b",
            r"\bcell\s+wall\s+hydrolases?\b",
            r"\bn-acetylmuramoyl-l-alanine\s+amidases?\b",
            r"\b[a-z0-9'-]*amidases?\b",
            r"\bmurein\s+(?:hydrolases?|endopeptidases?|dd-endopeptidases?|transglycosylases?)\b",
            r"\brz(?:-like|1|a|b)?\b",
            r"\b(?:host\s+|cell\s+)?lysis\b",
            r"\bnlp[- /]?p60\b",
            r"\bchap\s+domain\b",
            r"\bglycoside\s+hydrolase\s+family\s+(?:18|19|22|24|25|73|108)\b",
        ],
        "exclude": [
            r"\btail[- ]?(?:associated\s+)?(?:lysozymes?|lysins?|muramidases?|hydrolases?)\b",
            r"\btail\s+tip\s+lysins?\b",
            r"\btailspikes?\b",
            r"\bbaseplate[- ]?(?:lysozymes?|lysins?|hub)\b",
            r"\bvirion[- ]associated\s+lysozymes?\b",
            r"\binternal\s+virion\s+lysozymes?\b",
            r"\bhemolysins?\b",
            r"\bhaemolysins?\b",
            r"\benterolysins?\b",
            r"\bcytolysins?\b",
            r"\bleukocidins?\b",
            r"\bautolysins?\b",
            r"\bdeamidases?\b",
            r"\bamidotransferases?\b",
        ]
    },
    "capsid_head": {
        "label": "衣壳与头部形态发生 (Capsid & Head Morphogenesis)",
        "patterns": [
            r"\b(?:major|minor|prohead|procapsid|icosahedral|isometric)?\s*capsids?\b",
            r"\bportal\s*(?:proteins?|vertex)?\b",
            r"\bhead\s+(?:proteins?|completion|assembly|structural|maturation|morphogenesis|scaffolding|closure|decoration|stabilization|vertex|chaperones?|fibers?|fibres?)\b",
            r"\bhead[- ]?tail\s+(?:adaptors?|joining|connectors?|neck)\b",
            r"\b(?:head\s+|capsid\s+|prohead\s+)?maturation\s+proteases?\b",
            r"\bprohead\s*(?:proteases?|scaffolding|core|proteins?)?\b",
            r"\bprocapsids?\b",
            r"\bcoat\s+proteins?\b",
            r"\bvertex\s+proteins?\b",
            r"\bcapsomers?\b",
            r"\bdecoration\s+proteins?\b",
            r"\bscaffold(?:ing)?\s+proteins?\b",
            r"\b(?:major\s+|minor\s+)?virion\s+(?:structural|morphogenesis)\s+proteins?\b",
            r"\bencapsulins?\b",
            r"\bmu\s+protein\s+f\b",
            r"\bsh3\s+beta-barrel\s+fold\b",
        ],
        "exclude": []
    },
    "replication": {
        "label": "DNA 复制、重组与转录调控 (Replication, Recombination & Regulation)",
        "patterns": [
            r"\b(?:dna|rna)?\s*polymerases?\b",
            r"\bhelicases?\b",
            r"\bprimases?\b",
            r"\bprimase-helicases?\b",
            r"\bprimosomal\b",
            r"\breplication\s+(?:initiation|proteins?|factors?|organizers?|origins?)\b",
            r"\b(?:dna|rna)?\s*ligases?\b",
            r"\b(?:endo|exo|ribo|deoxyribo)nucleases?\b",
            r"\bhnh\b",
            r"\bgjy-yig\b",
            r"\bgiy-yig\b",
            r"\bvrr-nuc\b",
            r"\b(?:rnase|dnase)s?\b",
            r"\bssb\b",
            r"\bsingle[- ]strand(?:ed)?\s+(?:dna[- ]?)?(?:binding|annealing)\b",
            r"\bdna[- ]binding\b",
            r"\bmethyltransferases?\b",
            r"\bmethylases?\b",
            r"\btopoisomerases?\b",
            r"\bgyrases?\b",
            r"\bintegrases?\b",
            r"\bexcisionases?\b",
            r"\bexcise\b",
            r"\brecombinases?\b",
            r"\brecombination\b",
            r"\bresolvases?\b",
            r"\binvertases?\b",
            r"\btransposases?\b",
            r"\buvs[xyw]\b",
            r"\brec[abceft]\b",
            r"\brad5[12]\b",
            r"\b Nin[bcfg]\b",
            r"\bnin[bcfg]\b",
            r"\brdf\b",
            r"\b(?:anti[- ]?)?repressors?\b",
            r"\btranscriptio(?:n|nal)\b",
            r"\bsigma(?:\s+factors?|-[a-z0-9]+)\b",
            r"\banti[- ]?termination\b",
            r"\b(?:cro|ci|cii|ciii)\s*(?:proteins?|repressors?|regulators?|like)?\b",
            r"\bwhib\b",
            r"\bpar[abm]\b",
        ],
        "exclude": []
    },
    "packaging": {
        "label": "基因组包装与末端酶 (Packaging & Terminase)",
        "patterns": [
            r"\bterminases?\b",
            r"\bter[ls]\b",
            r"\b(?:dna|genome|headful|phage)\s+packaging\b",
            r"\bpackaging\s+(?:proteins?|enzymes?|machinery|atpases?|motors?|subunits?)\b",
            r"\bmaturases?\b",
            r"\bcos[- ]cleaving\b",
            r"\bpac\s+(?:proteins?|sites?|ases?)\b",
            r"\bpacases?\b",
        ],
        "exclude": []
    },
    "all": {
        "label": "全部匹配蛋白质 (All Matched CDS)",
        "patterns": [],
        "exclude": []
    }
}


def resolve_domain_names(category: str, product: str) -> Tuple[str, str, str]:
    """依据蛋白质功能分类与产品名称动态推导 N端、中段、C端 结构域名称"""
    p_lower = product.lower()

    if any(k in p_lower for k in ["tail tube", "tail sheath", "tube", "sheath", "major tail"]):
        return (
            "N-端环状聚合界面 (Ring Assembly N-term)",
            "中段管壁/鞘层骨架区 (Conduit Core)",
            "C-端末端对接区 (Distal Interface C-term)"
        )

    if category == "tail_fiber" or any(k in p_lower for k in ["tail fiber", "fiber", "spike", "receptor"]):
        return (
            "N-端基板锚定域 (Baseplate-binding N-term)",
            "中段三聚体骨架区 (Shaft / Trimer Core)",
            "C-端受体结合与纤突域 (Distal RBD / Spike)"
        )

    if category == "lysis" or any(k in p_lower for k in ["lysin", "lysozyme", "holin", "spanin", "peptidase", "endopeptidase"]):
        return (
            "N-端跨膜/催化活性域 (Catalytic / TM Domain)",
            "中段柔性连接区 (Flexible Linker)",
            "C-端细胞壁结合域 (Cell-Wall Binding CBD)"
        )

    if category == "capsid_head" or any(k in p_lower for k in ["capsid", "head", "coat", "portal", "scaffold", "vertex", "capsomer"]):
        return (
            "N-端衣壳组装前导域 (Prohead Assembly N-term)",
            "中段壳粒核心折叠区 (Capsomer Core)",
            "C-端外表面与顶角加固区 (Vertex / Surface C-term)"
        )

    if category == "replication" or any(k in p_lower for k in ["polymerase", "helicase", "primase", "ligase", "nuclease"]):
        return (
            "N-端调节与核酸外切域 (Regulatory / Exonuclease)",
            "中段核心催化活性中心 (Catalytic Polymerase Core)",
            "C-端核酸结合与夹钳区 (DNA-Binding Clamp)"
        )

    if category == "packaging" or any(k in p_lower for k in ["terminase", "packaging", "large subunit", "small subunit"]):
        return (
            "N-端 ATP 结合与驱动中心 (ATPase Engine N-term)",
            "中段能量转换与传动区 (Translocation Transducer)",
            "C-端 DNA 剪切与 Portal 结合区 (Endonuclease & Portal-binding)"
        )

    return (
        "N-端近端区域 (N-terminal Region)",
        "中央核心骨架区 (Central Core Region)",
        "C-端远端区域 (C-terminal Region)"
    )

