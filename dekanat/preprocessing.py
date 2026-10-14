"""Conservative text-line deskew; preview and evidence use rectified-page pixels."""
import cv2
import numpy as np
from PIL import Image


def estimate_skew(image):
    array = np.asarray(image)
    scale = min(1., 1200 / max(image.size))
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    if scale < 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale)
    edges = cv2.Canny(gray, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=45,
                            minLineLength=max(45, gray.shape[1]*.08), maxLineGap=12)
    if lines is None:
        return 0., 0
    angles, lengths = [], []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1,4):
        dx, dy = float(x2-x1), float(y2-y1)
        angle = np.degrees(np.arctan2(dy, dx))
        angle = (angle + 90) % 180 - 90
        if abs(angle) <= 35:
            angles.append(angle)
            lengths.append(np.hypot(dx, dy))
    if len(angles) < 5:
        return 0., 0
    angles, lengths = np.asarray(angles), np.asarray(lengths)
    # Dominant narrow angle cluster, weighted by segment length.
    bins = np.arange(-35, 36, 1.)
    support = np.array([lengths[np.abs(angles-a) <= 1.].sum() for a in bins])
    center = bins[support.argmax()]
    members = np.abs(angles-center) <= 1.5
    if members.sum() < 5 or lengths[members].sum() < lengths.sum()*.6:
        return 0., int(members.sum())
    angle = float(np.average(angles[members], weights=lengths[members]))
    return (angle if .7 <= abs(angle) <= 32 else 0.), int(members.sum())


def _deskew_page(image):
    angle, support = estimate_skew(image)
    width, height = image.size
    matrix = np.eye(3)
    corrected = image
    if angle:
        rotation = cv2.getRotationMatrix2D((width/2, height/2), angle, 1.)
        cos, sin = abs(rotation[0, 0]), abs(rotation[0, 1])
        new_width = int(np.ceil(height*sin + width*cos))
        new_height = int(np.ceil(height*cos + width*sin))
        rotation[0, 2] += (new_width-width)/2
        rotation[1, 2] += (new_height-height)/2
        corrected = Image.fromarray(cv2.warpAffine(np.asarray(image), rotation, (new_width, new_height),
                                                   flags=cv2.INTER_CUBIC, borderValue=(255,255,255)))
        matrix[:2] = rotation
    corrected.info["preprocessing"] = {"rotation_degrees": angle, "line_support": support,
        "input_size": [width, height], "output_size": list(corrected.size),
        "coordinate_space": "rectified_page_pixels", "rectified_to_input": np.linalg.inv(matrix).tolist(),
        "input_space": "EXIF-oriented image or rendered PDF page"}
    return corrected


def order_corners(points):
    points=np.asarray(points,dtype=np.float32).reshape(4,2)
    ordered=points[np.argsort(np.arctan2(points[:,1]-points[:,1].mean(),points[:,0]-points[:,0].mean()))]
    return np.roll(ordered,-int(np.argmin(ordered.sum(axis=1))),axis=0)


def find_page(image):
    """Find a bright four-corner sheet against a darker surrounding surface."""
    scale=min(1.,1200/max(image.size))
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    small=cv2.resize(gray,None,fx=scale,fy=scale) if scale<1 else gray
    blurred=cv2.GaussianBlur(small,(5,5),0)
    _,binary=cv2.threshold(blurred,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    edges=cv2.Canny(blurred,15,50)
    edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    candidates=[]
    for mask in (binary,edges):
        contours=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[-2]
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:25]:
            area=cv2.contourArea(contour)/(small.shape[0]*small.shape[1])
            if not .20<=area<=.94:continue
            approx=cv2.approxPolyDP(contour,.02*cv2.arcLength(contour,True),True)
            if len(approx)!=4 or not cv2.isContourConvex(approx):continue
            points=order_corners(approx)
            # Reject acute quadrilaterals and implausible page proportions.
            vectors=np.roll(points,-1,axis=0)-points
            lengths=np.linalg.norm(vectors,axis=1)
            if lengths.min()<small.shape[0]*.12:continue
            cosines=np.sum(vectors*np.roll(vectors,1,axis=0),axis=1)/(lengths*np.roll(lengths,1))
            if np.max(np.abs(cosines))>.85:continue
            width=max(lengths[0],lengths[2]);height=max(lengths[1],lengths[3])
            if not .42<=width/height<=1.8:continue
            inside=np.zeros_like(small);cv2.fillConvexPoly(inside,points.astype("int32"),255)
            inner=cv2.erode(inside,np.ones((15,15),np.uint8))>0
            ring=(cv2.dilate(inside,np.ones((25,25),np.uint8))>0)&(inside==0)
            if inner.sum()==0 or ring.sum()<100:continue
            contrast=float(np.median(small[inner])-np.median(small[ring]))
            if contrast<25:continue
            candidates.append((area*contrast,points/scale,contrast))
    if not candidates:return None
    _,points,contrast=max(candidates,key=lambda item:item[0])
    return points,contrast


def flatten_lighting(image):
    """Normalize a slowly varying background for OCR only, preserving dimensions."""
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    # Work at a bounded size for estimating background; interpolation retains pixel geometry.
    scale=min(1.,1000/max(image.size))
    small=cv2.resize(gray,None,fx=scale,fy=scale) if scale<1 else gray
    background=cv2.morphologyEx(small,cv2.MORPH_CLOSE,np.ones((31,31),np.uint8))
    background=cv2.GaussianBlur(background,(0,0),15)
    low,high=np.percentile(background,[10,90])
    apply=bool(high-low>28 or high<160)
    if not apply:return image,{"applied":False,"background_p10":float(low),"background_p90":float(high)}
    background=cv2.resize(background,(image.width,image.height)).astype(float)
    corrected=np.clip(gray.astype(float)*245/np.maximum(background,20),0,255).astype("uint8")
    result=Image.fromarray(cv2.cvtColor(corrected,cv2.COLOR_GRAY2RGB))
    return result,{"applied":True,"method":"background_division","background_p10":float(low),"background_p90":float(high),
                   "note":"Коррекция света для OCR; потерянные из-за блика символы не восстанавливаются."}


def quality_metrics(image):
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    h,w=gray.shape
    roi=gray[int(h*.12):int(h*.85),int(w*.08):int(w*.92)]
    sharpness=float(cv2.Laplacian(roi,cv2.CV_64F).var()) if roi.size else 0.
    dx=float(np.abs(cv2.Sobel(roi,cv2.CV_64F,1,0)).mean()) if roi.size else 0.
    dy=float(np.abs(cv2.Sobel(roi,cv2.CV_64F,0,1)).mean()) if roi.size else 0.
    direction_ratio=dx/max(.01,dy)
    warnings=[]
    if min(w,h)<650:warnings.append("Низкое разрешение: снимите документ крупнее.")
    if sharpness<35:warnings.append("Возможен расфокус или смаз: проверьте читаемость мелкого текста.")
    if dx+dy>1 and (direction_ratio<.5 or direction_ratio>3.):
        warnings.append("Возможен направленный смаз: снимите неподвижный документ повторно.")
    return {"laplacian_variance":sharpness,"gradient_direction_ratio":direction_ratio,
            "warnings":warnings,"review_required":bool(warnings),
            "scope":"Эвристика резкости/разрешения; не детектор всех бликов или доказательство читаемости."}


def rectify_page(image,photo=True):
    original_size=list(image.size);matrix=np.eye(3);page=image
    detection=find_page(image) if photo else None
    perspective={"applied":False,"reason":"Не найдены уверенные четыре угла листа на контрастном фоне"}
    if detection:
        points,contrast=detection
        lengths=np.linalg.norm(np.roll(points,-1,axis=0)-points,axis=1)
        width=max(2,round(float(max(lengths[0],lengths[2]))))
        height=max(2,round(float(max(lengths[1],lengths[3]))))
        matrix=cv2.getPerspectiveTransform(points,np.float32([[0,0],[width-1,0],[width-1,height-1],[0,height-1]]))
        page=Image.fromarray(cv2.warpPerspective(np.asarray(image),matrix,(width,height),flags=cv2.INTER_CUBIC,borderValue=(255,255,255)))
        perspective={"applied":True,"corners_input":points.tolist(),"border_contrast":contrast,
                     "method":"visible_sheet_quadrilateral","note":"Размер восстановлен по длинам сторон; истинный физический масштаб неизвестен."}
    corrected=_deskew_page(page)
    metadata=corrected.info["preprocessing"]
    inverse=np.linalg.inv(matrix)@np.asarray(metadata["rectified_to_input"])
    metadata.update(input_size=original_size,rectified_to_input=inverse.tolist(),perspective=perspective,
                    photo_mode=photo,quality=quality_metrics(corrected))
    return corrected
