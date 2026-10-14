"""Deterministic camera-like diagnostics; no claim of physical camera simulation."""
import cv2
import numpy as np
from PIL import Image, ImageFilter


def camera_view(image, view="front", seed=42):
    w,h=image.size
    canvas_w,canvas_h=round(w*1.4),round(h*1.3)
    corners={
        "front": [[.12,.10],[.87,.10],[.87,.90],[.12,.90]],
        "from_top": [[.25,.08],[.75,.08],[.91,.90],[.09,.90]],
        "from_bottom": [[.09,.10],[.91,.10],[.75,.92],[.25,.92]],
        "from_left": [[.10,.20],[.88,.06],[.88,.94],[.10,.80]],
        "from_right": [[.12,.06],[.90,.20],[.90,.80],[.12,.94]],
        "diagonal": [[.24,.04],[.88,.19],[.78,.94],[.08,.75]],
    }[view]
    dst=np.float32([[x*canvas_w,y*canvas_h] for x,y in corners])
    src=np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
    matrix=cv2.getPerspectiveTransform(src,dst)
    rng=np.random.default_rng(seed)
    background=np.clip(rng.normal(65,2,(canvas_h,canvas_w,3)),0,255).astype("uint8")
    page=cv2.warpPerspective(np.asarray(image),matrix,(canvas_w,canvas_h),borderValue=(0,0,0))
    mask=cv2.warpPerspective(np.full((h,w),255,np.uint8),matrix,(canvas_w,canvas_h))
    result=background.astype(float)*(1-mask[:,:,None]/255)+page.astype(float)*(mask[:,:,None]/255)
    return Image.fromarray(np.clip(result,0,255).astype("uint8"))


def illumination(image,mode):
    array=np.asarray(image).astype(float)
    h,w=array.shape[:2]; y,x=np.mgrid[0:h,0:w]; x=x/w; y=y/h
    if mode=="dark":
        array=array*.28
    elif mode=="shadow":
        factor=.22+.78/(1+np.exp(-(x-.45)*18))
        array=array*factor[:,:,None]
    elif mode=="spotlight":
        factor=.18+.82*np.exp(-((x-.65)**2/.25+(y-.3)**2/.35))
        array=array*factor[:,:,None]
    elif mode in ("flash_mild","flash_clipped"):
        strength=.65 if mode=="flash_mild" else 1.3
        spot=np.clip(strength*np.exp(-((x-.45)**2/.035+(y-.4)**2/.018)),0,1)
        array=array*(1-spot[:,:,None])+255*spot[:,:,None]
    elif mode=="warm":
        array=array*np.array([1.,.78,.55])
    return Image.fromarray(np.clip(array,0,255).astype("uint8"))


def motion_blur(image):
    kernel=np.zeros((9,9),np.float32);kernel[4,:]=1/9
    return Image.fromarray(cv2.filter2D(np.asarray(image),-1,kernel))


def conditions():
    return {
        "original":lambda x:x,
        **{f"perspective_{view}":lambda x,v=view:camera_view(x,v) for view in ["front","from_top","from_bottom","from_left","from_right","diagonal"]},
        "rotate_minus_30":lambda x:x.rotate(-30,Image.Resampling.BICUBIC,expand=True,fillcolor="white"),
        "defocus_1_2":lambda x:x.filter(ImageFilter.GaussianBlur(1.2)),
        "defocus_2_2":lambda x:x.filter(ImageFilter.GaussianBlur(2.2)),
        "motion_blur_9":motion_blur,
        **{name:lambda x,m=name:illumination(x,m) for name in ["dark","shadow","spotlight","flash_mild","flash_clipped","warm"]},
        "half_resolution":lambda x:x.resize((x.width//2,x.height//2),Image.Resampling.LANCZOS),
        "combined_view_shadow_blur":lambda x:illumination(camera_view(x,"diagonal").filter(ImageFilter.GaussianBlur(.8)),"shadow"),
    }
