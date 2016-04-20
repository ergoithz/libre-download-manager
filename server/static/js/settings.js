WEB_SOCKET_SWF_LOCATION = "/js/WebSocketMain.swf";
WEB_SOCKET_DEBUG = true;
GOOD_ENOUGH_HTML5_SUPPORT=(Prototype.Browser.IE)?(parseInt(navigator.appVersion.match(/MSIE ([\d.]+)/)[1])>9):true;
GOOD_HTML_BEHAVIOR=!(Prototype.Browser.IE); // IE scrolls before updating DOM, does not activate checkbox clicking on labels and so on
(function(){
    var socket = io.connect("/io"),
        cardhash = $H(), // paths without category
        path = "", // full path, including category
        updating = false,
        monitorized_types = $A(["text", "number"]),
        lastElementChildOf = (document.lastElementChild)?
            function(e){return e.lastElementChild}:
            function(e){
                for(var i=e.children.length-1;i>-1;i--)
                    if(e.children[i].nodeType==1)
                        return e.children[i];
                return null;
                },
        should_monitorize = function(e){
            return (monitorized_types.indexOf(e.type||null) !== -1);
            },
        caret_pos = function(e){
            var s;
            if (document.selection) { //IE
                e.focus();
                s = document.selection.createRange();
                s.moveStart('character', -e.value.length);
                return s.text.length;
                }
            if (e.selectionStart || e.selectionStart == '0') //firefox
                return e.selectionStart;
            return e.value.length;
            },
        control_name = function(e){
            if(e.length && e[0].tagName=="INPUT")
                return e[0].name;
            return e.name;
            },
        control_known_value = function(e){
            var s=e.getStorage();
            return s.last_known_value;
            },
        control_value = function(e, v){
            var current_value,
                current_input_value,
                new_value,
                new_input_value,
                default_value,
                default_input_value,
                tagname, typename;
            if(e.length){ // Select or list of radiobuttons
                // default_value
                default_value = null;
                default_input_value = 0;
                // current_value
                for(var i=0,j=e.length;i<j;i++){
                    if((e[i].tagName=="INPUT" && e[i].type.toLowercase()=="radio" && e[i].checked) || (e[i].tagName=="OPTION" && e[i].selected)){
                        current_value = e[i].value;
                        current_input_value = i;
                        break;
                    }
                }

                // new_value validation
                new_value = current_value;
                new_input_value = current_input_value;

                if(v!=undefined){
                    for(var i=0,j=e.length;i<j;i++){
                        if(((e[i].tagName=="INPUT" && e[i].type.toLowercase()=="radio") || e[i].tagName=="OPTION") && e[i].value==v){
                            new_value = v;
                            new_input_value = i;
                            break;
                        }
                    }
                }
            }else{
                tagname = e.tagName.toLowerCase();
                switch(tagname){
                    case "input":
                        typename = e.type.toLowerCase();

                        // default_value
                        default_value = "auto";
                        default_input_value = "auto";
                        if(e.hasAttribute("data-auto-value"))
                            default_input_value = e.readAttribute("data-auto-value");
                        else if(e.hasAttribute("placeholder")&&(GOOD_ENOUGH_HTML5_SUPPORT))
                            default_input_value = "";
                        else if((typename=="number")&&(e.hasAttribute("min"))){
                            default_input_value = e.readAttribute("min");
                            if(!isNaN(parseInt(default_input_value)))
                                default_value = parseInt(default_input_value);
                            }
                        else if(e.hasAttribute("data-numeric-input")){
                            default_input_value = parseInt(e.readAttribute("data-numeric-input").split(",")[0])||"auto";
                            if(!isNaN(parseInt(default_input_value)))
                                default_value = parseInt(default_input_value);
                            }

                        // current_value
                        current_value = e.value;
                        current_input_value = e.value;
                        if((current_value==default_value)||(current_input_value==default_input_value)){
                            current_value = default_value;
                            current_input_value = default_input_value;
                            }
                        else if(typename=="checkbox"||typename=="radio"){
                            current_value = e.checked;
                            current_input_value = e.checked;
                            }
                        else if(e.hasClassName("numeric-input")){
                            current_value = parseInt(current_input_value);
                            if(isNaN(parseInt(current_input_value))){
                                new_value = default_value;
                                new_input_value = default_input_value;
                                }
                            else if(e.hasClassName("netspeed-validator")&&(parseInt(current_input_value)<1)){
                                new_value = default_value;
                                new_input_value = default_input_value;
                                }
                            else if(e.hasAttribute("data-numeric-input")){
                                t = e.readAttribute("data-numeric-input").split(",");
                                if((t.length>0)&&t[0]){
                                    new_value = Math.max(parseInt(t[0]), current_value||-2147483647);
                                    new_input_value = new_value.toString();
                                    }
                                if((t.length>1)&&t[1]){
                                    new_value = Math.min(parseInt(t[1]), current_value||2147483647);
                                    new_input_value = new_value.toString();
                                    }
                                }
                            }

                        // new_value
                        if(v!=undefined){
                            if(v==default_value){
                                new_value = default_value;
                                new_input_value = default_input_value;
                                }
                            else if((typename=="checkbox")||(typename=="radio")||(typename=="submit")){
                                new_value = !!v;
                                new_input_value = !!v;
                                }
                            else
                                new_value = new_input_value = v;
                            }
                        break;
                    case "textarea": // the nice old textarea
                        // default_value
                        default_value = default_input_value = "";
                        // current_value
                        current_value = current_input_value = e.value;
                        // new_value
                        if(v!=undefined) new_value = new_input_value = v.toString();
                        break;
                    case "button":
                        // default_value
                        default_value = default_input_value = false;
                        // current_value
                        current_value = current_input_value = !!e.disabled;
                        // new_value
                        if(v!=undefined) new_value = new_input_value = !!v;
                        break;
                    }
                }
            if(new_value!=undefined){
                if(new_input_value!=current_input_value)
                    if(e.length) {
                        if(e[0].tagName=="INPUT")
                            e[new_input_value].checked = true;
                        else
                            e[new_input_value].selected = true;
                    } else if(tagname=="input"){
                        if((typename=="checkbox")||(typename=="radio"))
                            e.checked = new_input_value;
                        else if((typename=="button")||(typename=="submit"))
                            e.disabled = new_input_value;
                        else
                            e.value = new_input_value;
                        }
                    else if(tagname=="textarea")
                        e.value = new_input_value;
                    else if(tagname=="button")
                        e.disabled = new_input_value;
                return new_value;
                }
            if(current_value!=undefined)
                return current_value;
            if(default_value!=undefined)
                return default_value;
            return new_value;
            },
        cback_keypress_numkeys = function(evt){
            var char=String.fromCharCode(evt.which||evt.keyCode),
                e=evt.element();
            if(char){
                if(char=="-"){
                    if(caret_pos(e)>0) evt.stop();
                    else if(e.value.indexOf("-")!==-1) evt.stop();
                    }
                else if("0123456789".indexOf(char)===-1)
                    evt.stop();
                }
            },
        cback_change = function(evt, force){
            var e=evt.element(), s=e.getStorage(), v=control_value(e), d;
            if((v!=s.last_known_value)||(force===true)){ // Do not emit the same value twice
                s.last_known_value = v;
                d={};
                d[control_name(e)] = v;
                socket.emit("settings", d);
                }
            },
        cback_blur = function(evt){
            Event.fire(evt.element(), "change", null, false); // do not bubble
            },
        cback_submit = function(evt){
            cback_change(evt, true);
            evt.stop();
            },
        control_event = function (e){
            var t = "", et = "";
            if(e.length) {
                // should happen only with select or radiobuttons
                if(e[0].tagName=="INPUT" || e[0].tagName=="OPTION")
                    e.on("change", cback_change);
            } else {
                et = e.tagName.toLowerCase();
                switch(et){
                    case "input":
                        switch(e.type.toLowerCase()){
                            case "text":
                            case "number":
                                if(e.hasClassName("numeric-input"))
                                    e.on("keypress", cback_keypress_numkeys);
                            case "range":
                            case "select":
                            case "radio": // should not happen, but...
                            case "checkbox":
                                e.on("blur", cback_blur);
                                e.on("change", cback_change);
                                break;
                            case "button":
                            case "submit": // kinda toggle button
                                e.on("click", cback_submit);
                                break;
                            }
                        break;
                    case "textarea": // the nice old textarea
                        e.on("change", cback_change);
                        break;
                    case "button":
                        e.on("click", cback_submit);
                        break;
                    }
                }
            },
        has = function(obj, prop){
            return (typeof obj[prop] != "undefined");
            };
    socket.on("settings", function(data){
        if(!updating){ // Prevent calling twice
            updating = true;
            var f = document.forms[0], keys=$H(data).keys(), port_input_attributes;

            // Value update
            for(var k=0,l=keys.length;k<l;k++)
                if(has(f, keys[k]))
                    control_value(f[keys[k]], data[keys[k]]);

            // Disabling port inputs based on auto-ports
            if(data["auto-ports"]!=undefined){

                if(data["auto-ports"])
                    port_input_attributes = {"readonly":"readonly","disabled":"disabled"};
                else
                    port_input_attributes = {"readonly":null,"disabled":null};

                for(var k=0,l=f.length;k<l;k++)
                    try{
                        if(f[k].hasAttribute("name")&&(f[k].readAttribute("name").indexOf("port-")==0))
                            f[k].writeAttribute(port_input_attributes);
                        }
                    catch(e){
                        // IE7 SILENT ERROR with elements with some values
                        }
                }
            updating = false;
            }
        });
    // Connection control
    var dom_loaded=false, connected=false, updatecon=function(){
        if(dom_loaded&&connected) socket.emit("subscribe", "settings");
        },
        errorcon=function(){
            window.location.reload();
        },
        addcon=function(){
            connected=true;
            updatecon();
        },
        domloaded=function(){
            if(!dom_loaded){
                var categories = $("settings_categories").select("a"),
                    category_e = function(e){
                        /*
                         * Browser must scroll to category once clicked,
                         * so we need to adjust margins and paddings for
                         * some elements to get a nice behavior (section
                         * title on topleft of viewport) and do manual
                         * scrolling for fixing some scrolling problems
                         * caused by browser and not-so-well-written
                         * css.
                         */
                        var elm = e.findElement("a"),
                            hash = elm.href.substr(elm.href.indexOf("#")+1),
                            nospacing = hash == "anchor_general",
                            oldspacing = false,
                            target = $(hash),
                            targetbox,
                            container = $$(".settings-options")[0],
                            containerbox,
                            inner = container.children[0],
                            innerbox = inner.getBoundingClientRect(),
                            spacing = inner.offsetTop,
                            scrollspacing,
                            below,
                            scroll,
                            height;

                        // Unselected section appearance and reseting
                        // section title paddings
                        for(var i=0,j=categories.length;i<j;i++){
                            if((i>0)&&!oldspacing)
                                oldspacing = categories[i].up().hasClassName("settings-selected");
                            if(categories[i] != elm){
                                categories[i].up().toggleClassName("settings-selected", false);
                                $(categories[i].href.substr(categories[i].href.indexOf("#")+1)).style.paddingTop = 0;
                                }
                            }
                        // Selected section appearance and setting
                        // section title padding for scroll jump
                        elm.up().toggleClassName("settings-selected", true);
                        target.style.paddingTop = nospacing?0:spacing+"px";

                        // Scrolling fixes based on container margin
                        // for placing section title on top of viewport
                        // once scrolled.
                        targetbox = target.getBoundingClientRect();
                        containerbox = container.getBoundingClientRect();
                        scroll = targetbox.top - containerbox.top + container.scrollTop - spacing*nospacing;
                        height = innerbox.height||(innerbox.bottom-innerbox.top); // IE7 has no innerbox.height
                        below = height-scroll+spacing*(oldspacing?1:2);
                        height = containerbox.height||(containerbox.bottom-containerbox.top); // IE7 has no innerbox.height
                        lastElementChildOf(container).style.marginBottom = (below<height)?(height-below)+"px":0;

                        // Manual scrolling for special cases
                        if((hash=="anchor_general")||(!GOOD_HTML_BEHAVIOR)){
                            // Some browsers cannot scroll to anchor if float or relative elements
                            document.location.hash = hash;
                            container.scrollTop = scroll;
                            e.stop();
                            }
                        };
                categories.each(function(k){k.observe("click", category_e);});
                $("downloads-folder").writeAttribute({"readonly":"readonly","disabled":"disabled"});
                /*
                // input text to input number
                if(GOOD_ENOUGH_HTML5_SUPPORT){
                    var ninputs = $$(".numeric-input"), opts;
                    for(var i=0,l=ninputs.length;i<l;i++){
                        ninputs[i].writeAttribute("type", "number");
                        opts = (ninputs[i].readAttribute("data-numeric-input") || ",,").split(",");
                        if((opts.length>0)&&(!isNaN(parseInt(opts[0])))) ninputs[i].writeAttribute("min", opts[0]);
                        if((opts.length>1)&&(!isNaN(parseInt(opts[1])))) ninputs[i].writeAttribute("max", opts[1]);
                        if((opts.length>2)&&(!isNaN(parseInt(opts[2])))) ninputs[i].writeAttribute("step", opts[2]);
                        }
                    }
                */
                var input_groups = [
                    $(document.forms[0]).getInputs(),
                    $(document.forms[0]).select("button"),
                    $(document.forms[0]).select("select")
                    ];
                for(var i=0,l=input_groups.length;i<l;i++)
                    input_groups[i].each(control_event);
                dom_loaded=true;
                updatecon();
                }
        };
    socket.on('connect', addcon);
    socket.on('reconnect', addcon);
    socket.on('disconnect', errorcon);
    socket.on('error', errorcon);
    document.observe("dom:loaded", domloaded);
    }());
