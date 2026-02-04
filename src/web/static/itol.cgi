<!DOCTYPE html>

<html lang="en">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="author" content="Ivica Letunic">
<meta name="keywords" content="phylogenetic tree annotation,tree viewer,phylogenetic tree">
<meta name='description' content='phylogenetic tree viewer and annotation tool'>
<link rel="apple-touch-icon" sizes="57x57" href="/apple-touch-icon-57x57.png?v=3">
<link rel="apple-touch-icon" sizes="60x60" href="/apple-touch-icon-60x60.png?v=3">
<link rel="apple-touch-icon" sizes="72x72" href="/apple-touch-icon-72x72.png?v=3">
<link rel="apple-touch-icon" sizes="76x76" href="/apple-touch-icon-76x76.png?v=3">
<link rel="apple-touch-icon" sizes="114x114" href="/apple-touch-icon-114x114.png?v=3">
<link rel="apple-touch-icon" sizes="120x120" href="/apple-touch-icon-120x120.png?v=3">
<link rel="apple-touch-icon" sizes="144x144" href="/apple-touch-icon-144x144.png?v=3">
<link rel="apple-touch-icon" sizes="152x152" href="/apple-touch-icon-152x152.png?v=3">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon-180x180.png?v=3">
<link rel="icon" type="image/png" href="/favicon-32x32.png?v=3" sizes="32x32">
<link rel="icon" type="image/png" href="/android-chrome-192x192.png?v=3" sizes="192x192">
<link rel="icon" type="image/png" href="/favicon-96x96.png?v=3" sizes="96x96">
<link rel="icon" type="image/png" href="/favicon-16x16.png?v=3" sizes="16x16">
<link rel="manifest" href="/manifest.json?v=3">
<link rel="mask-icon" href="/safari-pinned-tab.svg?v=3">
<link rel="shortcut icon" href="/favicon.ico?v=3">
<meta name="msapplication-TileColor" content="#00aba9">
<meta name="msapplication-TileImage" content="/mstile-144x144.png?v=3">
<meta name="theme-color" content="#ffffff">

<title>iTOL: Interactive Tree Of Life</title>
    <link rel="stylesheet" href="/js/vendor/fa/css/all.min.css">
    <link rel="stylesheet" href="/css/font/css/itol3.css">
    <script src="/js/vendor/jquery-3.5.1.min.js"></script>
    <script src="/js/vendor/popper.min.js"></script>

    <link href="/js/vendor/tippy-light-border.css" rel="stylesheet" type="text/css"/>
    <script src="/js/vendor/jquery.filedrop2.min.js"></script>


    <script src="/js/vendor/bs/js/bootstrap.bundle.min.js"></script>
    <link href="/js/vendor/bs/css/bootstrap.min.css" rel="stylesheet" type="text/css"/>

    <script src="/js/vendor/jspanel/jspanel.min.js" type="text/javascript"></script>
    <script src="/js/vendor/jspanel/jspanel.modal.min.js" type="text/javascript"></script>
    <script src="/js/vendor/jspanel/jspanel.hint.min.js" type="text/javascript"></script>
    <link href="/js/vendor/jspanel/jspanel.min.css" rel="stylesheet" type="text/css"/>

    <script src="/js/vendor/featherlight.min.js" type="text/javascript"></script>
    <link href="/js/vendor/featherlight.min.css" rel="stylesheet" type="text/css"/>

    <script src="/js/vendor/bootstrap4-toggle.min.js" type="text/javascript"></script>
    <link href="/js/vendor/bootstrap4-toggle.min.css" rel="stylesheet" type="text/css"/>

    <script src="/js/vendor/bootstrap-select.min.js" type="text/javascript"></script>
    <link href="/js/vendor/bootstrap-select.min.css" rel="stylesheet" type="text/css"/>

    <script src="/js/vendor/spectrum.min.js" type="text/javascript"></script>
    <link href="/js/vendor/spectrum.min.css" rel="stylesheet" type="text/css"/>
    <script src="/js/vendor/rainbowvis.js" type="text/javascript"></script>

    <script src="https://ajax.googleapis.com/ajax/libs/webfont/1.6.26/webfont.js"></script>
    <script src="/js/vendor/webFonts.js"></script>

    <script src="/js/vendor/Sortable.js"></script>
    <script src="/js/vendor/jquery-sortable.js"></script>

    <script src="/js/vendor/hull.js"></script>
    <script src="/js/vendor/decimal.min.js"></script>
    <script src="/js/vendor/paper-core.js"></script>
    <script src="/js/vendor/biojs-io-newick.min.js"></script>

<!--batch export issues with ej2, so they are set in ITOLGEN-->

<script src="/js/vendor/ej2/itol/scripts/ej2-itol.min.js" type="text/javascript"></script><link href="/js/vendor/ej2/itol/styles/bootstrap4.css" rel="stylesheet" type="text/css"/><script src='/js/itol_gen.min.js?ver=7.0055'></script><link rel='stylesheet' type='text/css' href='/css/itol6.css?ver=7.0055' media='screen' /><link rel='stylesheet' type='text/css' href='/css/itol_viewer6.css?ver=7.00551770005966' media='screen' /></head>
<body>
<nav id='mainNav' class="user-select-none navbar py-0 fixed-top navbar-light navbar-expand-md bg-primary">
    <a href="/" class="navbar-brand"><img height='25px' src="/img/itol_logo.png" alt="logo"/></a>
    <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#itolMainNav">
        <span class="navbar-toggler-icon"></span>
    </button>
    <div class="navbar-collapse collapse justify-content-stretch" id="itolMainNav">
        <ul class="navbar-nav">
<li class='nav-item px-md-2 active'> <a class="nav-link" href="/itol.cgi"><img src="/img/control_head.png"  alt=""> <span class="navTxt2">Tree of Life</span></a></li>
<li  id='uploadHead' class='nav-item px-md-2 '><a class='nav-link' href='/upload.cgi'><i class='fad fa-upload'></i> <span class='navTxt'>Upload</span></a></li><li class='nav-item px-md-2'> <a class="nav-link" href="/shared_projects.cgi"><i class='fad fa-share-alt'></i> <span class="navTxt2">Data sharing</span></a></li>
<li class='nav-item px-md2 dropdown '>
                           <a class='nav-link dropdown-toggle' href='#' id='helpDropdown' role='button' data-toggle='dropdown' aria-haspopup='true' aria-expanded='false'>
                            <i class='far fa-question-circle'></i> <span class='navTxt2'>Help</span>
                           </a>
                           <div class='dropdown-menu' aria-labelledby='helpDropdown'>
                             <a class='dropdown-item' href='/help.cgi'><i class='far fa-question-circle'></i> Help pages</a>
                             <a class='dropdown-item' href='/video_tutorial.cgi'><i class='far fa-video'></i> Video tutorials</a>
                             <a class='dropdown-item' href='/gallery.cgi'><i class='far fa-image'></i> Tree gallery</a>
                             <div class='dropdown-divider'></div>
                             <a class='dropdown-item' href='/pricing.cgi'><i class='fad fa-user-unlock'></i> Subscription information</a>
                             <div class='dropdown-divider'></div>
                             <a class='dropdown-item' href='/about.cgi'><i class='far fa-envelope'></i> About & Contact</a>
                             <a class='dropdown-item' href='/version_history.cgi'><i class='far fa-history'></i> Version history</a>
                           </div>
                         </li>        </ul>
        <ul class="navbar-nav ml-auto">
<li style='display:none' id='hdrTreeSearchBut' class='uboxShow nav-item px-md2'><a class='nav-link' href='#' onclick='popPtreeSearch()'><i class='fad fa-search'></i> <span class='navTxt2'>Search</span></a></li>
                <li style='display:none' class='uboxShow nav-item px-md2 dropdown'>
                  <a class='nav-link dropdown-toggle' href='#' id='userDropdown' role='button' data-toggle='dropdown' aria-haspopup='true' aria-expanded='false'>
                   <i class='fad fa-users-cog'></i>  <span id='hdrUname' class='navTxt2'></span>
                  </a>
                     <div class='dropdown-menu  dropdown-menu-right' aria-labelledby='userDropdown'>
                     <a class='dropdown-item' href='/userInfo.cgi'><i class='fad fa-users-cog'></i> User account page</a>
                     <div class='dropdown-divider'></div>
                    <a class='dropdown-item' href='/login.cgi?logout=1'><i class='fad fa-sign-out-alt'></i> Sign out</a>
                    </div><li  id='loginHeadBut' class='uboxHide nav-item px-md-2'><a class='nav-link' href='#' onclick='return  popLogin()'><i class='fad fa-sign-in-alt'></i> <span class='navTxt2'>Sign in</span></a></li><li  id='regHeadBut' class='uboxHide nav-item px-md-2'><a class='nav-link' href='/itol_account.cgi'><i class='fad fa-user-plus'></i> <span class='navTxt2'>Register</span></a></li>        </ul>
    </div>
</nav>


<div id='tooltip'><h1 id='tooltipTitle'></h1><div id='tooltipBody'></div></div>


<!--control dialog-->
<ul id="controlmenu"></ul>
<ul id="nodemenu"></ul>
<ul id="leafmenu"></ul>
<ul id="movingmenu"></ul>
<ul id="viewmenu"></ul>
<ul id="undomenu"></ul>
<ul id="tnodemenu"></ul>
<ul id="tleafmenu"></ul>
<ul id="keymenu"></ul>

<div id='controlBox' style="max-width: 450px;visibility: hidden">
<div>
          <ul class="nav nav-tabs "  style='min-width: 400px;' id='controlTabs' role="tablist">
              <li class="nav-item"><a id='basic-tab' class="nav-link active" data-toggle="tab" role="tab" href="#basic-control" aria-controls="basic-control" aria-selected="true">Basic</a></li>
              <li class="nav-item"><a id='advanced-tab' class="nav-link" data-toggle="tab" role="tab" href="#advanced-control" aria-controls="advanced-control">Advanced</a></li>
              <li class="nav-item"><a id='dataset-tab' class="nav-link" data-toggle="tab" role="tab" href="#dataset-control" aria-controls="dataset-control" aria-selected="true">Datasets</a></li>
              <li class="nav-item"><a id='export-tab' class="nav-link" data-toggle="tab" role="tab" href="#export-control" aria-controls="export-control" aria-selected="true">Export</a></li>
            </ul>
</div>
    <div class="tab-content">
        <div id="basic-control" class="px-0 pt-1 tab-pane fade show active" role="tabpanel" aria-labelledby="basic-tab">
         <table id="basicControlTable">
                <tr><th>Mode</th><td colspan="4">
                       <div id='modeBox' class="btn-group btn-group-toggle btn-group-sm pruneOff" data-toggle="buttons">
                       <label style='width: 33%' class="btn btn-control active">
                           <input type="radio" name="modeS" id="mode2" onclick="l1l1(2)" autocomplete="off" checked> Circular
                       </label>
                       <label style='width: 33%' class="btn btn-control">
                           <input type="radio" name="modeS" id="mode1" onclick="l1l1(1)" autocomplete="off"> Rectangular
                       </label>
                       <label style='width: 33%' class="btn btn-control">
                           <input type="radio" name="modeS" id="mode3" onclick="l1l1(3)" autocomplete="off"> Unrooted
                       </label>
                         </div>
                         </td></tr>

                 <tr class="controlSectionRow"><th id="modeCell" rowspan="6">Mode options</th>
                     <th class="optionLabel">Rotation:</th>
                     <td colspan="3"><div class="inputSuffix"><input id="rotation" type="number" title="" value="210" step="10" min="0" max="360" size='3' /><span class='suffixTop'>°</span></div></td>
                 </tr>
                  <tr class="mH mV2">
                    <th class="optionLabel">Arc:</th>
                    <td colspan="3"><div class="inputSuffix pruneOff"><input id="arc" value="350" type="number" title="" step="10" min="0" max="360" size='3' /><span class='suffixTop'>°</span></div></td>
                    </tr>
                  <tr class="mH mV3" data-tip="Number of '<b>equal-daylight</b>' algorithm iterations (maximum of 5) to perform on the unrooted tree display, which spreads the nodes and increases branch visibility. Labels should be switched off, since they will overlap.<p>When set to 0, the standard '<b>equal-angle</b>' algorithm is used.">
                    <th class="optionLabel">Equal-daylight:</th>
                    <td colspan="3"><div class="inputSuffix"><input id="lllII1I1Level"  value="0" type="number" title="" step="1" min="0" max="5" size='3' /><span>iterations</span></div></td>
                  </tr>
                  <tr class="hideNoBrl">
                    <th class="optionLabel">Branch lengths:</th>
                    <td colspan="3" class='pruneOff'>
                        <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                            <label class="w-50 btn btn-control active" >
                                <input type="radio" name="labelDisplay" id="branchLen1" onclick="l1IIII(0)" autocomplete="off" checked> Use
                            </label>
                            <label class="w-50 btn btn-control">
                                <input type="radio" name="labelDisplay" id="branchLen2" onclick="l1IIII(1)" autocomplete="off"> Ignore
                            </label>
                        </div>
                  </tr>
                  <tr  class="mH mV2 mV1">
                    <th class="optionLabel">Invert tree:</th>
                    <td colspan="3" class='pruneOff'>
                        <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                            <label class="w-50 btn btn-control active" >
                                <input type="radio" name="invertC" id="invert1" onclick="llll1lI(1)" autocomplete="off"> Yes
                            </label>
                            <label class="w-50 btn btn-control">
                                <input type="radio" name="invertC" id="invert2" onclick="llll1lI(0)" autocomplete="off" checked> No
                            </label>
                        </div>
                    </td>
                  </tr>
                  <tr id="slantRow"  class="mH mV1">
                    <th class="optionLabel">Slanted:</th>
                    <td colspan="3" class='pruneOff'>
                        <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                            <label class="w-50 btn btn-control active" >
                                <input type="radio" name="slantedC" id="slanted1" onclick="I1lll1ll(1)" autocomplete="off"> Yes
                            </label>
                            <label class="w-50 btn btn-control">
                                <input type="radio" name="slantedC" id="slanted2" onclick="I1lll1ll(0)" autocomplete="off" checked> No
                            </label>
                        </div>
                    </td>
                  </tr>
                 <tr class="controlSectionRow"><th>Labels</th>
                     <td></td>
                     <td colspan="3">
                           <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                               <label class="w-50 btn btn-control active" >
                                   <input type="radio" name="labelDisplay" id="label1" onclick="I11II(1)" autocomplete="off" checked> Display
                               </label>
                               <label class="w-50 btn btn-control">
                                   <input type="radio" name="labelDisplay" id="label0" onclick="I11II(0)" autocomplete="off"> Hide
                               </label>
                           </div>
                     </td>
                 </tr>

                 <tr class="controlSectionRow mLabH"><th rowspan="6">Label options</th>
                 <th class="optionLabel">Font:</th>
                 <td colspan='3'>
                     <table style="width:100%">
                         <tr>
                             <td style="width:99%">
                                 <select id="fontName" name="fontName" onchange='l11llIIl()' class="selectpicker" data-container='body' data-width="100%" data-style="btn-control btn-sm">
                                     <option data-content="<span style='font-family:Arial'>Arial</span>">Arial</option>
                                     <option data-content="<span style='font-family:Verdana'>Verdana</span>">Verdana</option>
                                     <option data-content="<span style='font-family:Courier'>Courier</span>">Courier</option>
                                     <option data-content="<span style='font-family:Courier New'>Courier New</span>">Courier New</option>
                                     <option data-content="<span style='font-family:Times New Roman'>Times New Roman</span>">Times New Roman</option>
                                     <option data-content="<span style='font-family:Georgia'>Georgia</span>">Georgia</option>
                                     <option data-content="<span style='font-family:Impact'>Impact</span>">Impact</option>
                                     <option data-content="<span style='font-family:Monotype Corsiva'>Monotype Corsiva</span>">Monotype Corsiva</option>
                                 </select>
                             </td><td><button data-tip='Load additional fonts from the Google Web Fonts collection' onclick='IlIIll()' class="btn btn-control btn-sm"><i class="far fa-plus"></i></button></td>
                         </tr>
                     </table>
                    </td>
                 </tr>

                 <tr class="mLabH">
                     <th class="optionLabel">Font style:</th>
                     <td><div style='min-width: 75px' class="inputSuffix"><input id="fontSize" value="20" type="number" title="" min='0' step="1" size='3' /><span>px</span></div>
                       </td>
                     <td><input id="defaultLabelColor" /></td>
                     <td><div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                         <label class="btn btn-control active" >
                             <input type="checkbox"  id="fontStyleBold" onchange="IIIIII1()" autocomplete="off"> <i class="far fa-bold"></i>
                         </label>
                         <label class="btn btn-control" >
                             <input type="checkbox"  id="fontStyleItalic" onchange="IIIIII1()" autocomplete="off"> <i class="far fa-italic"></i>
                         </label>
                         <label id='fontSizeLockLbl' class="btn btn-control" data-tip="Lock the font size and prevent automatic font size calculation. Manually specified font size will be used.">
                             <input type="checkbox"  id="fontSizeLock" onchange="l11llIl()" autocomplete="off"><i class="fad"></i>
                         </label>
                     </div>
                     </td>
                 </tr>
                 <tr id='lblAlignRow' class="mLabH hideNoBrl hideIgnBrl">
                     <th class="optionLabel">Position:</th>
                     <td colspan='3'>
                         <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                             <label  style='width:50%' class="btn btn-control active">
                                 <input type="radio" name="labelC" id="labelC1" onclick="l1lIl1(1)" autocomplete="off" checked>Aligned
                             </label>
                             <label style='width:50%'  class="btn btn-control">
                                 <input type="radio" name="labelC" id="labelC0" onclick="l1lIl1(0)" autocomplete="off">At tips
                             </label>
                         </div>
                     </td>
                 </tr>

                 <tr class="mLabH mH mV1 mV2 mAlH"  data-tip='Labels can be aligned on the tree side (left), or towards the external datasets (right)'>
                     <th class="optionLabel">Alignment:</th>
                     <td colspan="3">
                         <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                         <label  style='width:50%' class="btn btn-control active">
                             <input type="radio" name="labelAlignC" id="labelAlign1"  onclick="l11111ll(1)" autocomplete="off" checked>Left
                         </label>
                         <label  style='width:50%' class="btn btn-control">
                             <input type="radio" name="labelAlignC" id="labelAlign0" onclick="l11111ll(0)" autocomplete="off">Right
                         </label>
                     </div>
                     </td>
                 </tr>
                  <tr class="mLabH" data-tip='When turned on, labels will be rotated automatically to make them readable on all sides of the tree.'>
                        <th class="optionLabel" >Rotation:</th>
                        <td colspan='3'>
                               <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                   <label style='width:50%' class="btn btn-control active">
                                       <input type="radio" name="labelRot" id="labelRot1" onclick="IlII1l(1)" autocomplete="off" checked>On
                                   </label>
                                   <label style='width:50%'  class="btn btn-control">
                                       <input type="radio" name="labelRot" id="labelRot2" onclick="IlII1l(0)" autocomplete="off">Off
                                   </label>
                               </div>
                        </td>
                     </tr>

                 <tr class="mLabH" data-tip="Shift the leaf labels farther from or closer to the tree.">
                     <th class="optionLabel">Shift:</th>
                      <td colspan='3'><div class="inputSuffix"><input id="labelShift" value="0" type="number" title="" step="10" size='3' /><span>px</span></div></td>
                 </tr>

                 <tr class="controlSectionRow"><th rowspan="3">Branch options</th>
                     <th class="optionLabel">Line style:</th>
                     <td><div class="inputSuffix"><input id="lineWidth"  value="1" type="number" title="" min='0' step="0.5" size='3' /><span>px</span></div></td>
                     <td><input id="defaultBranchColor" /></td>
                      <td class="mH mV1 mV2">
                         <div  class="btn-group btn-group-toggle btn-group-sm pruneOff" data-toggle="buttons">
                           <label class="btn btn-control active" data-tip='Connections between nodes are straight lines.'>
                               <input type="radio" name='curvedC' id="curved0" onclick="lII1l1I1(0)" autocomplete="off" checked><i class="fad fa-draw-square"></i>
                           </label>
                           <label class="btn btn-control"  data-tip='Connections between nodes are curves.'>
                               <input type="radio"  name='curvedC' id="curved1" onclick="lII1l1I1(1)" autocomplete="off"><i class="fad fa-bezier-curve"></i>
                           </label>
                         </div>
                       </td>
                 </tr>
                 <tr><th class="optionLabel">Color gradient:</th>
                       <td colspan="3">
                           <div  style='min-width: 210px' class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                               <label class="btn btn-control active"data-tip="Branch color will be a gradient from the ancestor towards node's own color" >
                                   <input type="radio" name='branchGradC' id="branchGrad1" onclick="I1l1(1)" autocomplete="off">On
                               </label>
                               <label class="btn btn-control" data-tip='Branch color will be uniform, even if the ancestor has a different color'>
                                   <input type="radio"  name='branchGradC' id="branchGrad2" onclick="I1l1(0)" autocomplete="off" checked>Off
                               </label>
                           </div>
                       </td>
                 </tr>
                 <tr data-tip="Set the style of the lines connecting the tips of the tree and the leaf text labels (or external datasets).">
                     <th class="optionLabel">Dashed lines:</th>
                     <td><div class="inputSuffix"><input id="dashesWidth"  value="0.3" type="number" title="" min='0' step="0.1" size='3' /><span>px</span></div></td>
                     <td colspan="1"><input id="dashesColor" />  </td>
                     <td>
                         <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                         <label class="btn btn-control active" >
                             <input type="radio" name='dashedType' id="dashedType1" onclick="III11(1)" autocomplete="off" checked><i class="far fa-ellipsis-h"></i>
                         </label>
                         <label class="btn btn-control" >
                             <input type="radio"  name='dashedType' id="dashedType0" onclick="III11(0)" autocomplete="off"><i class="far fa-minus"></i>
                         </label>
                     </div></td>
                 </tr>
               </table>
            </div>

            <div id="advanced-control" class="px-0 pt-1 tab-pane fade show" role="tabpanel" aria-labelledby="advanced-tab">
                <div id="advancedWrap">
                    <table id="advControlTable">
                        <tr class="mH mV1 mV2" data-tip="Stretch the tree vertically or horizontally. In the circular display mode, the vertical factor is not available, use the horizontal factor to increase the total tree radius."><th>Scaling factors:</th>
                            <td><div class="inputSuffix pruneOff"><input type='number' title='' id='inp_scale_horizontal' value='1' step='0.5' min="0" /><span>x horiz.</span></div></td>
                            <td><div class="inputSuffix pruneOff"><input type='number' title='' id='inp_scale_vertical' value='1' step='0.5' min="0"/><span>x vert.</span></div></td>
                        </tr>
                        <tr class="mH mV2 hideNoInv" data-tip='Use this parameter to increase or decrease the inner tree radius in inverted circular mode'><th>Inverted circle size:</th><td colspan="2">
                            <div class="inputSuffix pruneOff"><input type='number' title='' id='inp_circle_size_inverted' value='0' step="100"  /><span>px inc./dec.</span></div>
                        </td></tr>
                        <tr  class="mH mV1 mV2">
                           <th>Leaf sorting:</th>
                            <td colspan="2">
                                <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control active" data-tip='Branches with fewer leaf nodes are sorted towards the top of the tree.'>
                                        <input type="radio" name="leafS" id="leafSort1" onclick="llIIlIl(1)" autocomplete="off" checked> Default
                                    </label>
                                    <label class="w-50 btn btn-control" data-tip='Leaves are displayed in the original order, as they appear in the tree file.'>
                                        <input type="radio" name="leafS" id="leafSort2" onclick="llIIlIl(2)" autocomplete="off"> None
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr  class="mH mV1 mV2">
                            <th>Invert sort order:</th>
                            <td colspan="2">
                                <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control active">
                                        <input type="radio" name="leafSinv" id="leafSortInv1" onclick="lIl11III(true)" autocomplete="off" checked> Yes
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="leafSinv" id="leafSortInv2" onclick="lIl11III(false)" autocomplete="off"> No
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr>
                        <th id='brMetaDisplayHead' class="advTableHeader" colspan="3">Branch metadata display</th>
                        </tr>
                        <tr data-tip="Display internal node IDs/labels directly on the branches">
                            <th>Node IDs:</th>
                            <td colspan="2">
                                <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control active" >
                                        <input type="radio" name="branchIdC" id="idDisplay1" onclick="llII11I(1)" autocomplete="off" > Display
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="branchIdC" id="idDisplay0" onclick="llII11I(0)" autocomplete="off" checked> Hide
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr id='brIdShowSel' style='display:none' >
                            <th style="vertical-align: top">
                                <a onclick='l1IIll("brIdShowSel")' class='toggleAdvBut' id="brIdShowSelExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("brIdShowSel")'><span id='brIdShowSelNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                <div id='brIdShowSelTable' class="advSubTable">
                                    <table><tr><th>Font:</th><td><div class="inputSuffix"><input type='number' title='' id='branchIDLabelFontSize' min="0" step="1" value='10' style='min-width: 50px'/><span>px</span></div></td><td><input id='branchIDLabelColor' /></td><td><div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons"><label class="btn btn-control active" ><input type="checkbox"  id="branchIDLabelBold" autocomplete="off"> <i class="far fa-bold"></i></label><label class="btn btn-control" ><input type="checkbox"  id="branchIDLabelItalic" autocomplete="off"> <i class="far fa-italic"></i></label></div></td></tr>
                                        <tr data-tip="Display the label next to the branch, or above it"><th>Next to branch:</th><td colspan="3"><input type='checkbox' id='branchIDLabelNext' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>
                                        <tr data-tip="When labels are displayed next to the branch, this value is used as horizontal shift in pixels"><th>Position on branch:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='branchIDLabelPosition' step="10" value='50' /><span>%</span></div></td></tr>
                                        <tr><th>Vertical shift:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='branchIDLabelShift' step="1" value='0' /><span>px</span></div></td></tr>
                                        <tr><th>Label background:</th><td colspan="3"><input type='checkbox' id='branchIDLabelBackground' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>
                                        <tr><th>Background border:</th><td colspan="2"><div class="inputSuffix"><input type='number' title='' id='branchIDLabelBorderWid' min="0" step="0.2" value='0' /><span>px</span></div></td><td><input id='branchIDLabelBorderColor' /></td></tr>
                                        <tr><th>Background color:</th><td class="colFWid" colspan="3"><input id='branchIDLabelBackgroundColor' /></td></tr>
                                        <tr><th>Rounded corners:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='branchIDLabelBackgroundRadius' min='0' step="1" value='0' /><span>px</span></div></td></tr>
                                        <tr data-tip="Labels will be displayed only on clades belonging to one of the selected taxonomic classes. Node class can be specified in the LABELS annotation file, or by using the iTOL annotation editor. phyloT generated trees, or trees with automatically assigned taxonomy have node classes available as well."><th>Class filter:</th><td colspan="3"><select onchange='I1lIlIl1()' multiple id="branchIDClassSelector"></select></td></tr>

                                    </table>
                                </div>
                            </td>
                        </tr>
                        <tr class="hideNoBrl">
                            <th>Branch lengths:</th>
                            <td colspan="2">
                                <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control active" >
                                        <input type="radio" name="branchC" id="blDisplay1" onclick="IIlI1(1)" autocomplete="off" > Display
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="branchC" id="blDisplay0" onclick="IIlI1(0)" autocomplete="off" checked> Hide
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr id='blFontSizeSel' style='display:none' >
                            <th style="vertical-align: top">
                                <a onclick='l1IIll("blFontSizeSel")' class='toggleAdvBut' id="blFontSizeSelExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("blFontSizeSel")'><span id='blFontSizeSelNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                  <div id='blFontSizeSelTable' class="advSubTable">
                                        <table><tr><th>Font:</th><td><div class="inputSuffix"><input style='min-width: 50px' type='number' title='' id='branchlengthLabelFontSize' min="0" step="1" value='10' /><span>px</span></div></td><td><input id='branchlengthLabelColor' /></td><td><div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons"><label class="btn btn-control active" ><input type="checkbox"  id="branchlengthLabelBold" autocomplete="off"> <i class="far fa-bold"></i></label><label class="btn btn-control" ><input type="checkbox"  id="branchlengthLabelItalic" autocomplete="off"> <i class="far fa-italic"></i></label></div></td></tr>
                                            <tr><th>Position on branch:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='branchlengthLabelPosition' step="10" value='50' /><span>%</span></div></td></tr>
                                            <tr><th>Vertical shift:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='branchlengthLabelShift' step="1" value='0' /><span>px</span></div></td></tr>
                                            <tr><th>Round to:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='branchlengthLabelRounding' step="1" min='0' value='0' /><span>decimals</span></div></td></tr>
                                            <tr><th>Sci. notation:</th><td colspan="3"><input type='checkbox' id='branchlengthLabelSci' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>
                                            <tr data-tip='Display node ages instead of raw branch length values. Farthest leaf will have the age of zero. Age increases as nodes get closer to the tree root.'><th>Display as age:</th><td colspan="3"><input data-tip='Display node ages instead of raw branch length values. Farthest leaf will have the age of zero. Age increases as nodes get closer to the tree root.' type='checkbox' id='branchlengthLabelAge' data-width='100%' data-style="itol" data-toggle="toggle" data-size="xs" /></td></tr>
                                            <tr><th>Label background:</th><td colspan="3"><input type='checkbox' id='branchlengthLabelBackground' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>
                                            <tr><th>Background border:</th><td colspan="2"><div class="inputSuffix"><input type='number' title='' id='branchlengthLabelBorderWid' min="0" step="0.2" value='0' /><span>px</span></div></td><td><input id='branchlengthLabelBorderColor' /></td></tr>
                                            <tr><th>Background color:</th><td class="colFWid" colspan="3"><input id='branchlengthLabelBackgroundColor' /></td></tr>
                                            <tr><th>Rounded corners:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='branchlengthLabelBackgroundRadius' min='0' step="1" value='0' /><span>px</span></div></td></tr>
                                        </table>
                                    </div>
                                </td>
                        </tr>
                        <tr id='bootstrapHeader' class="hideNoBs">
                            <th>Bootstraps  / metadata:</th>
                            <td colspan="2">
                                <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control active" >
                                        <input type="radio" name="bootC" id="bootstrap1" onclick="Illl(1)" autocomplete="off" > Display
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="bootC" id="bootstrap0" onclick="Illl(0)" autocomplete="off" checked> Hide
                                    </label>
                                </div>
                            </td>
                        <tr id='bootstrapOptions' class="hideNoBs" style='display:none' >
                            <th style="vertical-align: top">
                                <a onclick='l1IIll("bootstrapOptions")' class='toggleAdvBut' id="bootstrapOptionsExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("bootstrapOptions")'><span id='bootstrapOptionsNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                <div id='bootstrapOptionsTable' class="advSubTable">
                                    <table>
                                        <tr>
                                            <th>Data source:</th>
                                            <td colspan="3"><select id='metadataSource' onchange='IIl1I1lI(true)'></select></td>
                                        </tr>
                                        <tr class="mNumHead">
                                            <th>Display range:</th>
                                            <td><input style="max-width:75px" type="number" id="bootValueMin" title="" step="any" /></td><td style="text-align:center">to</td><td style="text-align:right"><input style="max-width:75px" type="number" id="bootValueMax" title="" step="any" /></td>
                                        </tr>
                                        <tr id='multiRangeDef' style="display:none" data-tip='Define separate threshold ranges for different metadata sources.  '>
                                            <th>Multiple ranges:</th>
                                            <td colspan="3"><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control' onclick='l11l1I()'>Define ranges</button></td>
                                        </tr>
                                        <tr class="mNumHead bsTypHide bsTyp1 bsTyp3" data-tip='Create automatic legend for the current metadata source and display type. When symbols are used, symbol size in the legend will exactly match the symbol size in the tree at the current zoom level. To update the size, toggle the legend display.'>
                                            <th>Legend:</th>
                                            <td colspan="3"><input type='checkbox' id='metaBootLegend' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td>
                                        </tr>
                                    </table>

                                    <div id='metadataNumeric'>
                                        <div id='bootstrapOptB' class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons" data-tip="Select the type of metadata display:<ul><li><b>Symbol</b> : displayed on the tree branch<li><b>Text</b>: value displayed as a text label below the branch<li><b>Color</b> : branch colors are calculated from the metadata values<li><b>Width</b> : branch widths are calculated from the metadata values</ul>">
                                            <label class="w-25 btn btn-control active" >
                                                <input type="radio" name="bootOpt" id="bootstrapOpt1" onclick="l11lI1I(1)" autocomplete="off" checked> Symbol
                                            </label>
                                            <label class="w-25 btn btn-control">
                                                <input type="radio" name="bootOpt" id="bootstrapOpt2" onclick="l11lI1I(2)" autocomplete="off"> Text
                                            </label>
                                            <label class="w-25 btn btn-control">
                                                <input type="radio" name="bootOpt" id="bootstrapOpt3" onclick="l11lI1I(3)" autocomplete="off"> Color
                                            </label>
                                            <label class="w-25 btn btn-control">
                                                <input type="radio" name="bootOpt" id="bootstrapOpt4" onclick="l11lI1I(4)" autocomplete="off"> Width
                                            </label>
                                        </div>
                                        <div id='bootstrapSymbolOpt' class="bootOptions bootOption1 btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                            <label class="w-25 btn btn-control active" >
                                                <input type="radio" name="bootSym" id="bootstrapSym1" onclick="ll1IIII1(1)" autocomplete="off" checked> <i class="far fa-circle"></i>
                                            </label>
                                            <label class="w-25 btn btn-control">
                                                <input type="radio" name="bootSym" id="bootstrapSym2" onclick="ll1IIII1(2)" autocomplete="off"> <i class="far fa-triangle"></i>
                                            </label>
                                            <label class="w-25 btn btn-control">
                                                <input type="radio" name="bootSym" id="bootstrapSym3" onclick="ll1IIII1(3)" autocomplete="off"> <i class="far fa-square"></i>
                                            </label>
                                            <label class="w-25 btn btn-control">
                                                <input type="radio" name="bootSym" id="bootstrapSym4" onclick="ll1IIII1(4)" autocomplete="off"> <i class="far fa-star"></i>
                                            </label>
                                        </div>
                                        <div class='bootOptions bootOption1'>
                                            <table class='bootSymOptions'>
                                                <tr><th>Fill color:</th><td id="bootSymbolColorCl"><input type='text' id='bootSymbolColor' value='rgba(255,255,225,0.8)' /></td></tr>
                                                <tr><th>Border color:</th><td class="colFWid"><input type='text' id='bootSymbolBorderColor' value='rgba(255,255,225,0.8)' /></td></tr>
                                                <tr><th>Border width:</th><td class="colFWid"><div class="inputSuffix"><input type='number' id='bootSymbolBorderWid' title="" min="0" step="0.2" value='1' /><span>px</span></div></td></tr>
                                                <tr data-tip='Minimum metadata value will use this symbol size. Note that it can be larger than the maximum value specified below.'>
                                                    <th>Minimum size:</th>
                                                    <td><div class="inputSuffix"><input type='number' id='bootSymbolMinSize' title="" step="1" value='5' /><span>px</span></div></td>
                                                </tr>
                                                <tr data-tip='Maximum metadata value will use this symbol size. Note that it can be smaller than the minimum value specified above.'>
                                                    <th>Maximum size:</th>
                                                    <td><div class="inputSuffix"><input type='number' id='bootSymbolMaxSize' title="" step="1" value='15' /><span>px</span></div></td>
                                                </tr>
                                                <tr><th>Position on branch:</th>
                                                    <td><div class="inputSuffix"><input type='number' id='bootSymbolPosition' title="" step="10" value='50' /><span>%</span></div></td>
                                                </tr>
                                            </table>
                                        </div>
                                        <div class='bootOptions bootOption2'>
                                            <table>
                                                <tr><th>Font:</th><td><div class="inputSuffix"><input style='min-width: 50px' type='number' title='' id='bootLabelFontSize' step="1" value='10' /><span>px</span></div></td><td style='min-width: 50px' id="bootLabelColorCl"><input type='text' id='bootLabelColor' value='#000000' /></td><td><div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons"><label class="btn btn-control active" ><input type="checkbox"  id="bootLabelBold" autocomplete="off"> <i class="far fa-bold"></i></label><label class="btn btn-control" ><input type="checkbox"  id="bootLabelItalic" autocomplete="off"> <i class="far fa-italic"></i></label></div></td></tr>
                                                <tr><th>Position on branch:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='bootLabelPosition' step="10" value='50' /><span>%</span></div></td></tr>
                                                <tr><th>Vertical shift:</th><td colspan="3"><div class="inputSuffix"><input type='number' id='bootLabelShift' title='' step="1" value='0' /><span>px</span></div></td></tr>
                                                <tr data-tip='All values will be multiplied by this factor'><th>Scale by factor:</th><td colspan="3"><div class="inputSuffix"><input type='number' id='bootLabelPercentFactor'  step="any" /><span>x</span></div></td></tr>
                                                <tr><th>Round to:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='bootLabelRounding' step="1" min='0' value='0' /><span>decimals</span></div></td></tr>
                                                <tr><th>Scientific notation:</th><td colspan="3"><input type='checkbox' id='bootLabelSci' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>
                                                <tr data-tip='If selected, a <b>%</b> sign will be appended to the label'><th>Display as %:</th><td colspan="3"><input type='checkbox' id='bootLabelPercent' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>
                                                <tr data-tip='If multiple numeric metadata values are present, they will all be displayed at once, separated by <b>&#47;</b> signs'><th>Show all values:</th><td colspan="3"><input type='checkbox' id='bootLabelShowAll' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td><tr>
                                                <tr><th>Label background:</th><td colspan="3"><input type='checkbox' id='bootLabelBackground' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>
                                                <tr><th>Background border:</th><td colspan="2"><div class="inputSuffix"><input type='number' title='' id='bootLabelBorderWid' min="0" step="0.2" value='0' /><span>px</span></div></td><td><input id='bootLabelBorderColor' /></td></tr>
                                                <tr><th>Background color:</th><td colspan="3" class="colFWid"><input id='bootLabelBackgroundColor' /></td></tr>
                                                <tr><th>Rounded corners:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='bootLabelBackgroundRadius' min='0' step="1" value='0' /><span>px</span></div></td></tr>
                                            </table>
                                        </div>
                                        <div class='bootOptions bootOption3'>
                                            <table>
                                                <tr data-tip="Starting gradient color, assigned to the minimum metadata value"><th style="width:99%">Minimum:</th><td><input type='text' id='bootColorMin' value='#ff0000' /></td>
                                                <tr data-tip="If switched on, two separate gradients can be defined, from the minimum value to the midpoint, and from the midpoint to the maximum metadata value"><th>Midpoint:</th><td style="white-space: nowrap"><input  id='bootMidColBut' type='checkbox' data-width='75px' data-style="itol" data-toggle="toggle" data-size="xs" /><span id='bootMidColSel'><input type='text' id='bootColorMid' value='#ffff00' /></span></td>
                                                <tr data-tip="Ending gradient color, assigned to the maximum metadata value"><th>Maximum:</th><td><input type='text' id='bootColorMax' value='#0000ff' /></td></tr>
                                            </table>
                                        </div>
                                        <div class='bootOptions bootOption4'>
                                            <table>
                                                <tr data-tip="Branches outside the selected metadata range will use this branch width."><th>Default width:</th><td><div class="inputSuffix"><input type='number' id='bootWidthDefSize' min='0' value='1' step='1' title=''/><span>px</span></div></td></tr>
                                                <tr data-tip="Minimum metadata value will use this branch width. Note that it can be larger than the maximum value below."><th>Minimum width:</th><td><div class="inputSuffix"><input type='number' id='bootWidthMinSize' min='0' value='1' step='1' title=''/><span>px</span></div></td></tr>
                                                <tr data-tip="Maximum metadata value will use this branch width. Note that it can be smaller than the minimum value above."><th>Maximum width:</th><td><div class="inputSuffix"><input type='number' id='bootWidthMaxSize' min='0'  value='10' step='1' title='' /><span>px</span></div></td></tr>
                                            </table>
                                        </div>
                                    </div>
                                    <div id='metadataOther' style='display:none'>
                                        <div id='metaOtherOptB' class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons" data-tip="Select the type of display for non-numeric metadata:<ul><li><b>Text</b>: value displayed as a text label below the branch<li><b>Color</b> : branch colors are set from pre-defined categories</ul>">
                                            <label class="w-50 btn btn-control">
                                                <input type="radio" name="metaOtherOpt" id="metaOtherOpt2" onclick="l11lI1I(2)" autocomplete="off"> Text
                                            </label>
                                            <label class="w-50 btn btn-control">
                                                <input type="radio" name="metaOtherOpt" id="metaOtherOpt3" onclick="l11lI1I(3)" autocomplete="off"> Color
                                            </label>
                                        </div>
                                        <div class='metaOtherOptions metaOtherOption2' style='display:none'>
                                            <table>
                                                <tr><th>Font size:</th><td><div class="inputSuffix"><input type='number' id='metaOtherLabelFontSize' title="" step="1" min="0" value='10' /><span>px</span></div></td></tr>
                                                <tr><th>Position on branch:</th><td><div class="inputSuffix"><input type='number' id='metaOtherLabelPosition' title="" step="10" value='50' /><span>%</span></div></td></tr>
                                            </table>
                                        </div>
                                        <div class='metaOtherOptions metaOtherOption3'>
                                            <table>
                                                <tr><th>Category colors:</th><td><button style='line-height: 1' class='btn btn-block btn-sm btn-control' onclick='IllIIlIl()'>Define colors</button></td></tr>
                                            </table>
                                        </div>
                                    </div>
                                </div>
                            </td>
                        </tr>
                        <tr id='metaRangeHeader' class="hideNoBs" data-tip="Display range metadata (95% HPD, node age range and similar)">
                            <th>Range metadata:</th>
                            <td colspan="2">
                                <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control active" >
                                        <input type="radio" name="branchRngC" id="rngDisplay1" onclick="lII1l11I(1)" autocomplete="off" > Display
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="branchRngC" id="rngDisplay0" onclick="lII1l11I(0)" autocomplete="off" checked> Hide
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr id='brRngShowSel' style='display:none' >
                            <th style="vertical-align: top">
                                <a onclick='l1IIll("brRngShowSel")' class='toggleAdvBut' id="brRngShowSelExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("brRngShowSel")'><span id='brRngShowSelNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                <div id='brRngShowSelTable' class="advSubTable">
                                    <table><tr><th>Data source:</th><td colspan="3"><select id='rngMetadataSource' onchange='lllI1(true)'></select></td></tr>
                                    <tr data-tip="Position of the bar center relative to the branch."><th>Position on branch:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='rngMetadataPosition' step="10" value='50' /><span>%</span></div></td></tr>
                                    <tr><th>Vertical shift:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='rngMetadataShift' step="1" value='0' /><span>px</span></div></td></tr>

                                    <tr><th>Show bars:</th><td colspan="3"><input type='checkbox' id='rngMetadataShowBar' data-width='100%' data-style="itol" data-toggle="toggle" data-size="xs" /></td></tr>
                                    <tr><th>Max bar width:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='rngMetadataBarWid' min="0" step="20" value='100' /><span>px</span></div></td></tr>
                                    <tr><th>Bar height:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='rngMetadataBarHt' min="0" step="1" value='5' /><span>px</span></div></td></tr>
                                    <tr><th>Bar color:</th><td class="colFWid" colspan="3"><input id='rngMetadataBarColor' /></td></tr>
                                    <tr><th>Bar border:</th><td colspan="2"><div class="inputSuffix"><input type='number' title='' id='rngMetadataBarBorderWid' min="0" step="0.2" value='0' /><span>px</span></div></td><td><input id='rngMetadataBarBorderColor' /></td></tr>

                                    <tr><th>Show labels:</th><td colspan="3"><input type='checkbox' id='rngMetadataShowLabel' data-width='100%' data-style="itol" data-toggle="toggle" data-size="xs" /></td></tr>
                                    <tr><th>Label font:</th><td><div class="inputSuffix"><input style='min-width: 50px' type='number' title='' id='rngMetadataLabelFontSize' step="1" value='10' /><span>px</span></div></td><td style='min-width: 50px' id="rngMetadataLabelColorCl"><input type='text' id='rngMetadataLabelColor' value='#000000' /></td><td><div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons"><label class="btn btn-control active" ><input type="checkbox"  id="rngMetadataLabelBold" autocomplete="off"> <i class="far fa-bold"></i></label><label class="btn btn-control" ><input type="checkbox"  id="rngMetadataLabelItalic" autocomplete="off"> <i class="far fa-italic"></i></label></div></td></tr>
                                    <tr data-tip='Alignment of the labels relative to the bar start and end'><th>Label align:</th><td colspan="3"><select style='width:100%' id='rngMetadataLabelAlign'><option value='1'>outside</option><option value='2'>center</option><option value='3'>inside</option></select></td></tr>
                                    <tr data-tip='Shift the labels horizontally and vertically'><th>Label shift (X and Y):</th><td colspan='3'><table><tr><td style='width:50%'><div class='inputSuffix'><input id='rngMetadataLabelShiftX' type='number' step='1' value='0' title='' /><span>px</span></div></td><td><div class='inputSuffix'><input id='rngMetadataLabelShiftY' type='number' step='1' value='0' title='' /><span>px</span></div></td></tr></table></td></tr>
                                    <tr data-tip='All displayed label values will be multiplied by this factor'><th>Scale by factor:</th><td colspan="3"><div class="inputSuffix"><input type='number' id='rngMetadataLabelPercentFactor'  step="any" /><span>x</span></div></td></tr>
                                    <tr><th>Round to:</th><td colspan="3"><div class="inputSuffix"><input type='number' title='' id='rngMetadataLabelRounding' step="1" min='0' value='0' /><span>decimals</span></div></td></tr>
                                    <tr><th>Scientific notation:</th><td colspan="3"><input type='checkbox' id='rngMetadataLabelSci' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>

                                    </table>
                                </div>
                            </td>
                        </tr>

                        <tr class='hideIgnBrl hideNoBrl'>
                            <th class="advTableHeader" colspan="3">Tree scales</th>
                        </tr>
                        <tr class='mHide mVisible1 mVisible2 hideIgnBrl hideNoBrl'>
                            <th>Internal tree scale:</th>
                            <td colspan="2">
                                <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control active" >
                                        <input type="radio" name="intScaleC" id="intScale1" onclick="I11l1I1(1)" autocomplete="off" > Display
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="intScaleC" id="intScale0" onclick="I11l1I1(0)" autocomplete="off" checked> Hide
                                    </label>
                                </div>
                            </td>
                        <tr id='intScaleOptions' style='display:none' >
                            <th style="vertical-align: top">
                                <a onclick='l1IIll("intScaleOptions")' class='toggleAdvBut' id="intScaleOptionsExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("intScaleOptions")'><span id='intScaleOptionsNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                <div id='intScaleOptionsTable' class="advSubTable">
                                    <table style="width: 100%">
                                        <tr id="intScaleHd"><th colspan='2'>Branch length</th><th>Color</th><th><i class="fad fa-text"></i></th><th><i class="far fa-ellipsis-h"></i></th><th>Width</th></tr>
                                        <tr><td style='text-align: right;white-space: nowrap'>Interval 1</td><td><input style='width: 50px' type='number' id='internalScale1' title='' step="0.1" value='0' /></td><td style='min-width: 55px'><input type='text' id='internalScale1Color' /></td><td style='text-align: center'><input data-tip='Display label' type='checkbox' id='internalScale1Label' value='1' /></td><td style='text-align: center'><input data-tip='Dashed line' type='checkbox' id='internalScale1Dashed' value='1' /></td><td><div class="inputSuffix"><input style="max-width:75px" type='number' id='internalScale1Wid' step="any" value='1' min="0"/><span>px</span></div></td></tr>
                                        <tr><td style='text-align: right'>Interval 2</td><td><input style='width: 50px' type='number' id='internalScale2' title='' step="0.1" value='0' /></td><td><input type='text' id='internalScale2Color' /></td><td style='text-align: center'><input data-tip='Display label' type='checkbox' id='internalScale2Label' value='1' /></td><td style='text-align: center'><input data-tip='Dashed line' type='checkbox' id='internalScale2Dashed' value='1' /></td><td><div class="inputSuffix"><input style="max-width:75px"  type='number' id='internalScale2Wid' step="any" value='1' min="0" /><span>px</span></div></td></tr>
                                        <tr><td style='text-align: right'>Fixed</td><td><input  type='text' style='width: 50px' data-tip='Comma separated list of values. Scale lines will be displayed at those branch length distances from the tree root (or top, if the scale is inverted).' id='internalScaleFixed' value='' size='5' /></td><td><input type='text' id='internalScaleFixedColor' /></td><td style='text-align: center'><input data-tip='Display label' type='checkbox' id='internalScaleFixedLabel' value='1' /></td><td style='text-align: center'><input data-tip='Dashed line' type='checkbox' id='internalScaleFixedDashed' value='1' /></td><td><div class="inputSuffix"><input  style="max-width:75px" type='number' id='internalScaleFixedWid' step="any" value='1' min="0" /><span>px</span></div></td></tr>
                                        <tr data-tip="When inverted, scale starts at the farthest tree leaf instead of the tree root."><th style='vertical-align: middle' colspan='5'>Inverted scale</th><td ><input type='checkbox' id='internalScaleInvert' data-width='75px' data-style="itol" data-toggle="toggle" data-size="xs" data-on="Yes" data-off="No" /></td></tr>
                                        <tr><th style='vertical-align: middle' colspan='5'>Label font size</th><td><div class="inputSuffix"><input style='width:75px' type='number' id='internalScaleFontSize' value='10' min="0" step="1"  /><span>px</span></div></td></tr>
                                        <tr><th style='vertical-align: middle' colspan='5'>Label shift</th><td><div class="inputSuffix"><input style='width:75px' type='number' id='internalScaleLabelShift' value='0' step="5"  /><span>px</span></div></td></tr>
                                        <tr><th style='vertical-align: middle' colspan='5'>Draw grid</th><td><input type='checkbox' id='internalScaleGrid' checked='checked' data-width='75px' data-style="itol" data-toggle="toggle" data-size="xs" data-on="Yes" data-off="No"/></td></tr>
                                        <tr><th style='vertical-align: middle' colspan='5'>Draw axis</th><td><input type='checkbox' id='internalScaleAxis' checked='checked' data-width='75px' data-style="itol" data-toggle="toggle" data-size="xs" data-on="Yes" data-off="No"/></td></tr>
                                        <tr data-tip='Draw the scale labels and axis below the tree'><th style='vertical-align: middle' colspan='5'>Axis/labels below the tree</th><td><input type='checkbox' id='internalScaleAxisBelow' data-width='75px' data-style="itol" data-toggle="toggle" data-size="xs" data-on="Yes" data-off="No"/></td></tr>
                                        <tr><th id="timeScaleModeHd" colspan='6'>Time scale mode</th></tr>
                                        <tr data-tip='Set the time/numeric value for the tree root. All scale labels will be calculated based on this value, combined with the factor set below'><th style='vertical-align: middle' colspan='5'>Set root to:</th><td><input  style="width:75px" type='number'  step="any"  id='internalScaleRootValue' value='' /></td></tr>
                                        <tr data-tip='Branch lengths will be multiplied by this value when calculating the scale labels which are displayed.' ><th style='vertical-align: middle' colspan='5'>Scaling factor:</th><td ><input style="width:75px" type='number' step="any" id='internalScaleTimeScaling' value='' /></td></tr>
                                        <tr data-tip='After the scaling factor is applied, the label will be rounded to the selected number of decimals'><th style='vertical-align: middle' colspan='5'>Round to:</th><td><div class="inputSuffix"><input type='number' title='' id='internalScaleTimeScalingRound' step="1" min='0' value='' /><span>decimals</span></div></td></tr>
                                    </table>
                                </div>
                            </td>
                        </tr>
                        <tr class='hideIgnBrl hideNoBrl'>
                            <th>Tree scale box:</th>
                            <td colspan="2">
                                <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control active" >
                                        <input type="radio" name="treeScaleC" id="treeScale1" onclick="II1I1(1)" autocomplete="off" checked> Display
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="treeScaleC" id="treeScale0" onclick="II1I1(0)" autocomplete="off"> Hide
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr class='hideIgnBrl hideNoBrl' id='treeScaleOptions'>
                            <th style="vertical-align: top">
                                <a onclick='l1IIll("treeScaleOptions")' class='toggleAdvBut' id="treeScaleOptionsExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("treeScaleOptions")'><span id='treeScaleOptionsNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                <div id='treeScaleOptionsTable' class="advSubTable">
                                    <table>
                                        <tr><th>Label font size:</th><td><div class="inputSuffix"><input type='number' title="" id='treeScaleFontSize' value='12' min="1" step="1" /><span>px</span></div></td></tr>
                                        <tr><th>Label text:</th><td><input type='text' id='treeScaleLabel' value='Tree scale:' onchange="IlllI()"/></td></tr>
                                        <tr><th>Line width:</th><td><div class="inputSuffix"><input type='number' title="" id='treeScaleWidth' value='1' min="0" step="1" /><span>px</span></div></td></tr>
                                        <tr><th>Line color:</th><td id="treeScaleColT"><input id='treeScaleColor' value='#000000' /></td></tr>
                                        <tr data-tip='Set a fixed branch length value for the scale. Leave empty or set to 0 to use the automatic scale.'><th>Fixed value:</th><td><input style="width: 100%" type='number' id='treeScaleFixedValue' value='0' onchange="IlllI()" /></td></tr>
                                    </table>
                                </div>
                            </td>
                        </tr>

                        <tr>
                            <th class="advTableHeader" colspan="3">Node options</th>
                        </tr>

                        <tr>
                            <th>Leaf node symbols:</th>
                            <td colspan="2">
                                <div id='lfNodeSymBox' class="pruneOff btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control" >
                                       <input type="radio" name="lfNodeSymbolC" id="lfNodeSymbol1" onclick="lI11ll('leaf', 1)" autocomplete="off" checked> Display
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="lfNodeSymbolC" id="lfNodeSymbol0" onclick="lI11ll('leaf', 0)" autocomplete="off"> Hide
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr id='leafNodeSymbolOptions'>
                            <th style="vertical-align: top">
                                <a onclick='l1IIll("leafNodeSymbolOptions")' class='toggleAdvBut' id="leafNodeSymbolOptionsExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("leafNodeSymbolOptions")'><span id='leafNodeSymbolOptionsNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                <div id='leafNodeSymbolOptionsTable' class="advSubTable">
                                    <table>
                                        <tr><th>Shape:</th><td><select class='dsLegendShape' id='lfNodeSymbolShape'><option value='1' data-content="<i class='itolicon-sq'></i>">Square</option><option value='DI' data-content="<i class='itolicon-dia'></i>">Rhombus (diamond)</option><option value='2' data-content="<i class='itolicon-cir'></i>">Circle</option><option value='3' data-content="<i class='itolicon-star'></i>">Star</option><option value='4' data-content="<i class='itolicon-tri_r'></i>">Right triangle</option><option value='5' data-content="<i class='itolicon-tri_l'></i>">Left triangle</option></select></td></tr>
                                        <tr><th>Size:</th><td><div class="inputSuffix"><input type='number' title="" id='lfNodeSymbolSize' value='5' min="1" step="1" /><span>px</span></div></td></tr>
                                        <tr><th>Fill color:</th><td class="colFWid"><input id="lfNodeSymbolColor" value="#999999" /></td></tr>
                                        <tr><th>Border width:</th><td><div class="inputSuffix"><input type='number' title="" id='lfNodeSymbolBorder' value='1' min="0" step="0.2" /><span>px</span></div></td></tr>
                                        <tr><th>Border color:</th><td class="colFWid"><input id="lfNodeSymbolBorderColor" value="#000000" /></td></tr>
                                    </table>
                                </div>
                            </td>
                        </tr>
                        <tr>
                            <th>Internal node symbols:</th>
                            <td colspan="2">
                                <div id='intNodeSymBox' class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="w-50 btn btn-control" >
                                        <input type="radio" name="intNodeSymbolC" id="intNodeSymbol1" onclick="lI11ll('internal', 1)" autocomplete="off" checked> Display
                                    </label>
                                    <label class="w-50 btn btn-control">
                                        <input type="radio" name="intNodeSymbolC" id="intNodeSymbol0" onclick="lI11ll('internal',0)" autocomplete="off"> Hide
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr id='internalNodeSymbolOptions'>
                            <th style="vertical-align: top">
                                <a onclick='l1IIll("internalNodeSymbolOptions")' class='toggleAdvBut' id="internalNodeSymbolOptionsExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("internalNodeSymbolOptions")'><span id='internalNodeSymbolOptionsNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                <div id='internalNodeSymbolOptionsTable' class="advSubTable">
                                    <table>
                                        <tr><th>Node type:</th><td>
                                            <div id='intNodeSymTyp'  class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                                <label class="w-50 btn btn-control active" data-tip='Display symbols on all internal nodes'>
                                                    <input type="radio" name="intNodeSymbolCW" id="intNodeSymbolW1" onclick="llllIIlI(1)" autocomplete="off" checked> All
                                                </label>
                                                <label class="w-50 btn btn-control" data-tip='Display symbols on internal nodes which have only one child'>
                                                    <input type="radio" name="intNodeSymbolCW" id="intNodeSymbolW0" onclick="llllIIlI(0)" autocomplete="off"> One child
                                                </label>
                                            </div>
                                        </td></tr>
                                        <tr><th>Shape:</th><td><select class='dsLegendShape' id='intNodeSymbolShape'><option value='1' data-content="<i class='itolicon-sq'></i>">Square</option><option value='DI' data-content="<i class='itolicon-dia'></i>">Rhombus (diamond)</option><option value='2' data-content="<i class='itolicon-cir'></i>">Circle</option><option value='3' data-content="<i class='itolicon-star'></i>">Star</option><option value='4' data-content="<i class='itolicon-tri_r'></i>">Right triangle</option><option value='5' data-content="<i class='itolicon-tri_l'></i>">Left triangle</option></select></td></tr>
                                        <tr><th>Size:</th><td><div class="inputSuffix"><input type='number' title="" id='intNodeSymbolSize' value='5' min="1" step="1" /><span>px</span></div></td></tr>
                                        <tr><th>Fill color:</th><td class="colFWid"><input id="intNodeSymbolColor" value="#999999" /></td></tr>
                                        <tr><th>Border width:</th><td><div class="inputSuffix"><input type='number' title="" id='intNodeSymbolBorder' value='1' min="0" step="0.2" /><span>px</span></div></td></tr>
                                        <tr><th>Border color:</th><td class="colFWid" ><input id="intNodeSymbolBorderColor" value="#000000" /></td></tr>
                                    </table>
                                </div>
                            </td>
                        </tr>

                        <tr class="hideNoCol"><th>Collapsed clades:</th>
                            <td colspan="2">
                                <div id='colShapeBox' class="pruneOff btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                                    <label class="btn btn-control" data-tip='A triangle where two side lengths are proportional to the distances to node&#39;s closest and farthest child leaves.'>
                                        <input type="radio" name="colShape" id="collapsedShape1" onclick="l1llI11l(1)" autocomplete="off" checked> Triangle
                                    </label>
                                    <label class="btn btn-control" data-tip='A simple isosceles triangle with two equal sides.'>
                                        <input type="radio" name="colShape" id="collapsedShape2" onclick="l1llI11l(2)" autocomplete="off"> Iso. Triangle
                                    </label>
                                    <label class="btn btn-control">
                                        <input type="radio" name="colShape" id="collapsedShape3" onclick="l1llI11l(3)" autocomplete="off"> Circle
                                    </label>
                                </div>
                            </td>
                        </tr>
                        <tr class="hideNoCol">
                            <th style="vertical-align: top">
                            <a onclick='l1IIll("collapsedOption")' class='toggleAdvBut' id="collapsedOptionExp"><i class="far fa-chevron-square-down"></i></a>
                            </th>
                            <td colspan="2">
                                <a onclick='l1IIll("collapsedOption")'><span id='collapsedOptionNt' class='toggleAdvBut' style="display:none">Show details</span></a>
                                <div id='collapsedOptionTable' class="advSubTable">
                                    <table>
                                        <tr data-tip='Default fill color. If the collapsed node has branch line color specified, that same color will be used instead.'><th>Fill color:</th><td id="colFillColorCell"><input type='text' id='colFillColor' value="rgba(0,0,0,0.5)" /></td></tr>
                                        <tr data-tip='Vertical spacing or arc taken by each collapsed node can be set here. Value can be 0, 1 or 2. Setting it to zero will cause internal overlaps, but allows external datasets to align without gaps.'><th>Arc/vertical spacing:</th><td><div class="inputSuffix"><input type='number' title='' id='colSpacing' value="2" min="0" max="2" step="1" /><span>leaves</span></div></td></tr>
                                        <tr><th>Label font size factor:</th><td><div class="inputSuffix"><input type='number' title='' id='colFontSize' min="0" step="0.1" value="1.5" /><span>x</span></div></td></tr>
                                        <tr data-tip='Size control for circle and isosceles triangle. In unrooted mode, also controls the width of the regular triangle.'><th>Collapsed shape size:</th><td><div class="inputSuffix"><input type='number' title='' id='colShapeSize' min="0" step="5" value="30" /><span>px</span></div></td></tr>
                                        <tr id='hColT' data-tip='When switched on, the size of the collapsed nodes will be proportional to the number of leaves within'><th>Proportional sizing:</th><td><input onchange='IlII11()' type='checkbox' id='colShapeProportional' data-width='100%' data-style="itol"  data-toggle="toggle" data-size="xs" /></td></tr>
                                        <tr data-tip='Un-collapse all collapsed clades in the tree'><th>Un-collapse all:</th><td><button style='margin-bottom: -1px;line-height: 1' class='btn btn-sm btn-block btn-control' onclick='l1IIl1()'>Un-collapse all</button></td></tr>
                                    </table>
                                </div>
                            </td>
                        </tr>
                        <tr class='hideNoBrl' data-tip='Spacing and size of the lines marking any truncated nodes'>
                            <th>Truncated branches:</th>
                            <td><div class="inputSuffix"><input type='number' title='' id='truncatedWidth' value="10" step="1" min="0" /><span>px</span></div></td>
                            <td><div class="inputSuffix"><input type='number' title='' id='truncatedSpacing' value="5" step="1" min="0" max="10" /><span>px</span></div></td>
                        </tr>

                        <tr class='hideNoBrl' data-tip='Collapse all clades whose average branch length distance to their leaves is below this number'>
                            <th>Auto collapse clades:</th>
                            <td><div class="inputSuffix"><input type='number' title='' id='autoCollapseDist' value="0" step="0.1" min="0" /><span>&gt; avg.BRL</span></div></td>
                            <td><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control pruneOff' onclick='l1l11()'>Collapse</button></td>
                        </tr>
                        <tr class='hideNoBs' data-tip='Collapse all clades whose bootstrap value is below or above this number. If the direction is not specified (by adding a <b>&lt;</b> or <b>&gt;</b> sign), values below this number will be used. For multi-bootstrap or trees with node metadata, the source selected under bootstrap display section is used.'>
                           <th id='autoCollapseBootHead'></th>
                           <td><div class="inputSuffix"><input type='text' title='' id='autoCollapseBoot' value="0>" step="auto"  /><span>bootstrap</span></div></td>
                           <td><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control pruneOff' onclick='II1I()'>Collapse</button></td>
                       </tr>
                        <tr data-tip='Collapse all clades based on their assigned class. Node class can be specified in the LABELS annotation file, or by using the iTOL annotation editor. Trees with automatically assigned taxonomy have node classes available as well.'>
                            <th id='autoCollapseClassHead'></th>
                            <td><div class="inputSuffix"><select id='autoCollapseClass'></select></div></td>
                            <td><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control pruneOff' onclick='II1l1()'>Collapse</button></td>
                        </tr>
                        <tr class='hideNoBs' data-tip='Delete all nodes whose bootstrap value is below this number. For multi-bootstrap or trees with node metadata trees, the source selected under bootstrap display section is used. '>
                            <th>Delete branches:</th>
                            <td><div class="inputSuffix"><input type='number' title='' id='delBranchBoot' value="0" min="0" step="1"><span>&gt; bootstrap</span></div></td>
                            <td><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control pruneOff' onclick='lI1II()'>Delete</button></td>
                        </tr>
                        <tr>
                            <th class="advTableHeader" colspan="3">Other functions</th>
                        </tr>
                        <tr>
                            <th>Label functions:</th>
                            <td><button data-tip='Automatically define multiple font styles within labels.' style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control' onclick='II11l1l()'>Multi-style</button></td>
                            <td><button data-tip='Perform common editing functions on all labels at once' style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control' onclick='l1IllIIl()'>Bulk edit</button></td>
                        </tr>
                        <tr class='autoTaxFunc' data-tip='If your leaf node IDs are numeric NCBI taxonomy IDs or GTDB accession numbers, you can use this function to automatically assign the correct scientific names to all leaves and internal nodes in the tree.'>
                            <th>Auto assign taxonomy:</th>
                            <td><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control' onclick='ll1l1Il1()'>NCBI</button></td>
                            <td><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control' onclick='I1IIlII()'>GTDB</button></td>
                        </tr>
                        <tr>
                            <th>Root the tree midpoint:</th>
                            <td colspan="2"><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control' onclick='l11lIll()'>Midpoint root</button></td>
                        </tr>
                        <tr data-tip='Automatically create a timescale dataset based on the International Chronostratigraphic Chart'>
                            <th>Auto timescale:</th>
                            <td colspan="2"><button style='margin-bottom: -1px;line-height: 1' class='btn btn-block btn-sm btn-control' onclick='lI1I1()'>ICC geological timescale</button></td>
                        </tr>
                    </table>
                </div>
            </div>

        <div id="dataset-control" class="px-0 pt-1 tab-pane fade show" role="tabpanel" aria-labelledby="dataset-tab">
                <div class="p-1"><p class="alert alert-info">Click the cog icon (<i class='far fa-cog'></i>) next to any entry in the datasets panel to display its configuration options here.</p>
                <button class='btn btn-primary btn-block btn-sm' onclick='lIlIIlI()'><i class="fad fa-layer-plus"></i> Create a dataset</button>
                    <button class='btn btn-primary btn-block btn-sm' onclick='llIII11()'><i class="fad fa-upload"></i> Upload annotation files</button></div>
            </div>
            <div id="export-control" class="p-1 tab-pane fade show" role="tabpanel" aria-labelledby="export-tab">

                <table id="exportControlTable">
                    <tr><th>Format:</th><td>
                        <select class='form-control form-control-sm' id='exportFormat' onchange='ll1lI()'>
                            <optgroup label="Vector"><option value='svg' selected>SVG: Scalable Vector Graphics</option>
                            <option value='eps'>EPS: Encapsulated Postscript</option>
                            <option value='pdf'>PDF: Portable Document Format</option></optgroup><optgroup label='Bitmap'><option value='png'>PNG: Portable Network Graphics</option></optgroup>
                            <optgroup label='Text'><option value='newick'>Newick tree</option><option value='phyloxml'>phyloXML tree</option><option value='nexus'>NEXUS tree</option>
                                <option value='colors'>Colors and styles annotation</option><option value="collapse">Collapsed nodes list</option></optgroup>
                        </select>
                    </td></tr>
                    <tr class='exBmp'><th>Resolution:</th><td><div class="inputSuffix"><input type='number' title="" min="0" max="1000" step="20" id='export_dpi' value='120' /><span>dpi</span></div></td></tr>
                    <tr style='display:none' class='exVec exMar'><th>Margin:</th><td><div class="inputSuffix"><input type='number' title="" min="0" max="100" step="5" id='export_margin' value='0' /><span>mm</span></div></td></tr>
                    <tr class='exBmp exVec'><th>Export area:</th><td>
                        <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                            <label data-tip='Exported figure will exactly match what is currently visible in the browser. Note that this simply sets the SVG viewport, the complete drawing is still included (in vector formats).' class="w-50 btn btn-control active">
                                <input type="radio" name="exportAreaB" id="exportArea1" value='0' autocomplete="off" checked> Screen
                            </label>
                            <label data-tip="Exported figure will contain the complete tree and all visible datasets" class="w-50 btn btn-control">
                                <input type="radio" name="exportAreaB" id="exportArea2" value='1' autocomplete="off"> Full image
                            </label>
                        </div>
                    </td></tr>
                    <tr class='exTxt' id='metadataFormatRow' data-tip="If present in the tree, bootstraps/metadata will be exported as follows :<ul><li><b>simple</b>: single bootstrap value (depending on the original input tree this can be the original boostrap value, first bootstrap from multi-bootstrap values, or PROB value from MrBayes trees</li>
                    <li><b>multiple:</b> if multiple bootstrap values were present in the original tree, all of them will be included, separated with forward slash signs (/)</li>
                    <li><b>mrbayes</b>: all available metadata values will be exported using their original keywords</li><li><b>NXH</b>: all available metadata values will be exported using their original keywords</li></ul>"><th>Bootstraps/metadata:</th><td>
                        <select class='form-control form-control-sm' id='exportMetadataFormat' >
                            <option value='simple' selected>Simple</option>
                            <option value='multi'>Multiple</option>
                            <option value='mrbayes'>MrBayes</option>
                            <option value='nhx'>NHX</option>
                        </select>

                    </td></tr>
                    <tr class='exTxt'><th>Internal node IDs:</th><td>
                        <div class="btn-group btn-group-toggle btn-group-sm" data-toggle="buttons">
                            <label data-tip='Exported tree will contain internal node IDs (if these were present in the original file).' class="w-50 btn btn-control active">
                                <input type="radio" name="exportIntNodeB" id="exportIntNode1" value='1' autocomplete="off" checked> Include
                            </label>
                            <label data-tip="Exported tree will contain only bootstrap and branch length information (if present)." class="w-50 btn btn-control">
                                <input type="radio" name="exportIntNodeB" id="exportIntNode2" value='0' autocomplete="off"> Exclude
                            </label>
                        </div>
                    </td></tr>
                     <tr><th>File name:</th><td>
                            <input type='text' id='exportName' placeholder='optional' />
                      </td></tr>
                    <tr><td colspan='2' style='text-align: right'>
                        <button id='exButSh' data-tip='Add this export to the shared exports list for this tree. See the <b>Data sharing</b> page for details.' style='width: 49%' class='mt-2 btn btn-primary btn-sm ' onclick='II1llIIl(1)'><i class='fad fa-share-alt'></i> Share</button>
                        <button id='exButM' style='width: 49%' class='mt-2 btn btn-success btn-sm' onclick='II1llIIl(0)'><i class='fad fa-file-export'></i> Export</button>
                    </td></tr>
                    <tr id="exportQueue" style="display:none"><td colspan='2'><table><tr><td style="vertical-align: top; padding-right: 5px"><button class="btn btn-danger" style='white-space:nowrap; line-height: 1' onclick="lI11Il()"><span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Cancel job</button></td><td>Your job is in the export queue at <b>position <span id="queuePos">0</span></b>. The download will start automatically when the export is complete.</td></tr></table></td></tr>
                    <tr><td colspan="2" style='display:none' id='exportFallback'><p class="mt-2 mb-0 p-1 alert alert-info" >If the download did not start automatically, please <a id='exportFallbackLInk' href='#'>click here.</a></p></td></tr>
                </table>
                <p class='exCol alert alert-info mb-0'>This will create a plain text iTOL <b>COLORS</b> annotation file containing all branch and label style information and all defined colored ranges. You can drag and drop it onto the tree to restore its colors/styles later.</p>

                <iframe id="exportDownloader" src="" style="display:none; visibility:hidden;"></iframe>

            </div>
     </div>

</div>
<!--end control dialog -->



<canvas id="treeCanvas" data-paper-resize="true" data-paper-hidpi="on" style="width: 100%; height: 100%;"></canvas>

<div id='zoomControlBox' class='user-select-none'>
  <img id='zoomIn' src='/img/zoom-in.svg' alt='icon' data-tip='Zoom in' />
  <img id='zoomOut' src='/img/zoom-out.svg' alt='icon' data-tip='Zoom out' />
  <img id='zoomFit' src='/img/zoom-fit.svg' alt='icon' data-tip='Fit to screen' />
  <img src='/img/info.svg' alt='icon' id='treeInfoBut' />
  <img src='/img/search.svg' alt='icon' data-tip='Search tree nodes' id='treeSearchBut' />
  <img src='/img/annotate.svg' style='width: 25px; margin-top: 10px' alt='icon' data-tip='Manual annotations' id='annotateBut' />
</div>
<div id='helpPops' style='position: absolute; bottom: 25px; left: 10px;font-size: 1.5rem; color: #999' class='user-select-none'>
    <a id="keyHelp"><i class='fad fa-keyboard'></i></a>
</div>
<div id='colorTester' style='position:absolute; left:-1000px; top:-1000px'></div>
<pre id='cHelper' style='position:absolute; left:-1000px; top:-1000px'></pre>
<div id='filedrop-over' class="filedrop-modal"><div><button class="btn btn-sm btn-outline-secondary" onclick="closeDropModal()"><i class="far fa-times"></i></button><b>Drop one or more annotation files to visualize them.</b><br/>Make sure to use the template files provided in the help pages.</div></div>
<form id='uploadHelper' method='post' enctype="multipart/form-data"><input type='file' name="annoFile[]" multiple id='annoFiles' style='position:fixed;top:-1000px' /></form>
<div id="autocompleteHelper" style="display:none"><div id='nodeAutoCompleteRes'></div></div>

<div id='bout' style='display:block'>0</div>

<script src='/js/vendor/tippy.js'></script><script src='/js/itol_all.min.js?ver=7.0055'></script><script>tree_id='1'; var user_settings ={};</script><footer id='mainFooter' class='footer' style='text-align: center'><div style='margin-left:10px' class='small text-muted float-left'><span class='footHd'><b>Citation:</b> Letunic and Bork (2024) <i>Nucleic Acids Res</i> <a href='https://doi.org/10.1093/nar/gkae268'><b>doi: 10.1093/nar/gkae268</b></a> |</span> <a href='privacy.cgi'>Privacy Policy</a></div><div style='margin-right:10px' class='small text-muted float-right'>design & development: <a target='_blank' href='https://www.biobyte.de'>biobyte solutions</a></div></footer><div class='loading-modal'></div><script type='text/javascript'>var _paq = _paq || [];_paq.push(['disableCookies']); _paq.push(['trackPageView']);_paq.push(['enableLinkTracking']);(function() {var u='//tr-denbi.embl.de/heimdall/';_paq.push(['setTrackerUrl', u+'p.php']);_paq.push(['setSiteId', '6']);var d=document, g=d.createElement('script'), s=d.getElementsByTagName('script')[0];   g.type='text/javascript'; g.async=true; g.defer=true; g.src=u+'p.js'; s.parentNode.insertBefore(g,s);})();</script></body></html>