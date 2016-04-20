WEB_SOCKET_SWF_LOCATION = "/js/WebSocketMain.swf";
WEB_SOCKET_DEBUG = true;
(function(){
    var socket = io.connect("/io"),
        cardhash = {}, // paths without category
        path = "", // full path, including category
        reversed_card = null;
        has = function(obj, prop){
            return (typeof obj[prop] != "undefined");
            },
        fix_ellipsis_elements = [],
        fix_ellipsis_cache = {},
        fix_ellipsis_internal = function(el, original_text){
            if(!el.__ellipsis_do){
                // Stop ellipsis
                return false;
                }
            if(!is_topleft_visible(el)){
                // DOM not ready
                el.__ellipsis_timeout = window.setTimeout(function(){fix_ellipsis_internal(el);}, 10);
                return false;
                }
            var data=el.getStorage(), text=el.firstChild, orig_text=original_text||text.nodeValue;
            if(fix_ellipsis_cache[orig_text]){
                // Already ellipsized
                text.nodeValue = fix_ellipsis_cache[orig_text];
                return false;
                }
            var ext=el.lastChild;
            if((!data.ellipsizing)&&(!is_center_visible(ext))){
                data.ellipsizing = true;
                var end_text = "\u2026 ",
                    remove_end = orig_text.length-(ext.innerText||"").length-1,
                    current = orig_text,
                    steps = [];
                while (remove_end>0 && !is_center_visible(ext)){
                    if(fix_ellipsis_cache[current]){
                        // Current partially ellisized string is already ellipsized
                        text.nodeValue = steps[steps.length] = current = fix_ellipsis_cache[current];
                        break;
                        }
                    else if(!el.__ellipsis_do){
                        text.nodeValue = orig_text;
                        return;
                        }
                    remove_end-=1;
                    text.nodeValue = steps[steps.length] = current = orig_text.substring(0,remove_end)+end_text;
                    }
                if(remove_end < 1){
                    // If something went wrong, revert and retry
                    text.nodeValue = orig_text;
                    el.__ellipsis_timeout = window.setTimeout(function(){fix_ellipsis_internal(el, orig_text);}, 10);
                    }
                else{
                    // Good ellipsis, cache steps
                    fix_ellipsis_cache[orig_text] = current;
                    for(var i=0,l=steps.length-1;i<l;i++)
                        fix_ellipsis_cache[steps[i]] = current;
                    }
                delete data.ellipsizing;
                }
            },
        fix_ellipsis = function(el){
            el.__ellipsis_do = true;
            el.__ellipsis_timeout = -1;
            fix_ellipsis_elements.push(el);
            fix_ellipsis_internal(el);
            },
        multifix_ellipsis_wrapper = function(elm){
            return function(){fix_ellipsis_internal(elm)};
            },
        multifix_ellipsis = function(elements){
            for(var i=0, l=elements.length;i<l;i++){
                elements[i].__ellipsis_do = true;
                elements[i].__ellipsis_timeout = window.setTimeout(multifix_ellipsis_wrapper(elements[i]), 20*i);
                fix_ellipsis_elements.push(elements[i]);
                }
            },
        stop_ellipsis = function(){
            for(var i=0,l=fix_ellipsis_elements.length;i<l;i++){
                fix_ellipsis_elements[i].__ellipsis_do = false;
                window.clearTimeout(fix_ellipsis_elements[i].__ellipsis_timeout);
                }
            fix_ellipsis_elements = [];
            },
        is_center_visible = function(el){
            try{
                var r = el.getBoundingClientRect(),
                    x = (r.left + r.right)/2,
                    y = (r.top + r.bottom)/2;
                return document.elementFromPoint(x, y) === el;
                }
            catch(e){}
            return false;
            },
        is_topleft_visible = function(el){
            try{
                var r = el.getBoundingClientRect();
                return document.elementFromPoint(r.left+1, r.top+1) === el;
                }
            catch(e){}
            return false;
            },
        get_current_download = function(){
            var colons = path.indexOf(":"),
                firstslash = path.indexOf("/");
            if(colons==-1) return null;
            if(firstslash==-1) return path.substr(colons+1);
            return path.substr(colons+1, firstslash-colons-1);
            },
        get_current_category = function(){
            var colons = path.indexOf(":");
            if(colons==-1) return "all";
            return path.substr(0, colons)
            },
        assign_card_events = function(elm){
            // Click events
            var card = elm.getStorage()["data"],
                category = get_current_category();
            elm.on("click", ".a-image", function(e){
                socket.emit("open", category + ":" + card.path);
                e.stop();
                });
            elm.on("click", ".a-text", function(e){
                if(reversed_card) reversed_card.toggleClassName("reverse", false);
                elm.toggleClassName("reverse", true);
                reversed_card = elm;
                e.stop();
                // Deferred reverse event asign
                if(!card.reverse_events){
                    /*
                    var bubble = elm.select(".reverse-action-share .bubble")[0],
                        a = bubble.select(".share a"),
                        form = bubble.select("form")[0];
                    */
                    card.reverse_events = true;
                    elm.on("click", ".reverse-close", function(e){
                        elm.toggleClassName("reverse", false);
                        e.stop();
                        });
                    elm.on("click", ".reverse-action-folder a", function(e){
                        socket.emit("folder", category + ":" + card.path);
                        e.stop();
                        });
                    elm.on("click", ".reverse-action-delete a", function(e){
                        e.stop();
                        });
                    elm.on("click", ".reverse-action-play a", function(e){
                        socket.emit("open", category + ":" + card.path);
                        e.stop();
                        });
                    elm.on("click", ".reverse-action-delete a", function(e){
                        socket.emit("remove", category + ":" + card.path);
                        e.stop();
                        });
                    elm.on("click", ".reverse-action-share a", function(e){
                        bubble.toggleClassName("visible", true);
                        e.stop();
                        });
                    /*
                    bubble.on("click", ".bubble-close", function(e){
                        bubble.toggleClassName("visible", false);
                        e.stop();
                        });
                    bubble.on("click", ".cog", function(e){
                        e.stop();
                        });
                    a[0].on("click", function(e){ // facebook
                        e.stop();
                        });
                    a[1].on("click", function(e){ // twitter
                        e.stop();
                        });
                    form.on("action", function(e){ // share
                        e.stop(e);
                        });
                    */
                    elm.on("click", ".reverse-action-rename a", function(e){
                        socket.emit("rename", category + ":" + card.path);
                        e.stop(e);
                        });
                    elm.on("click", ".reverse-action-p2p a", function(e){ // Seed
                        e.stop(e);
                        });
                    }
                });
            },
        assign_category_events = function(elm){
            elm.on("click", "a", function(e){
                $("js_categories").select("li").each(function(li, i){
                    li.toggleClassName("play-selected", false);
                    });
                elm.toggleClassName("play-selected", true);
                socket.emit("open", elm.getStorage()["data"].path);
                e.stop();
                });
            },
        assign_breadcrumb_events = function(elm){
            elm.on("click", "a", function(e){
                socket.emit("open", elm.getStorage()["data"].path);
                e.stop();
                });
            },
        remove_cards = function(data){
            if (data.indexOf(get_current_download()) > -1)
                // Current card is removed, go to roots
                socket.emit("open", get_current_category());
            else
                // Remove cards
                var ta=$A(data);
                for(var i=0,l=ta.length;i<l;i++)
                    if(cardhash[ta[i]]){
                        cardhash[ta[i]].remove();
                        delete cardhash[ta[i]];
                        }
            },
        update_tasks = function(data){
            $("js_tasks").update(data);
            },
        update_path = function(data){
            cardhash = {};
            path = data;
            },
        update_breadcrumbs = function(data){
            var html="", c;
            for(var i=0, l=data.length;i<l;i++)
                html += data[i].html;
            $("js_breadcrumbs").update(html);
            c = $("js_breadcrumbs").childElements();
            for(var i=0, l=Math.min(c.length, data.length);i<l;i++){
                c[i].getStorage()["data"] = data[i];
                assign_breadcrumb_events(c[i]);
                }
            },
        update_categories = function(data){
            var p=$("js_categories"), c=p.childElements(), cl=c.length, li, nli, name;
            // Update current categories
            for(var i=0, j=cl;i<j;i++)
                if(i<data.length){
                    nli = c[i].getStorage()["data"] === undefined;
                    if(nli)
                        name = c[i].innerHTML.stripTags().toLowerCase().strip();
                    else
                        name = c[i].getStorage()["data"].name;
                    if(name==data[i].name)
                        li = c[i];
                    else{
                        c[i].replace(c[i], data[i].html);
                        li = p.childElements()[i]; // Element has been replaced
                        }
                    li.getStorage()["data"] = data[i];
                    li.toggleClassName("play-selected", data[i].selected);
                    if(nli) // Events seems to be preserved on replaces
                        assign_category_events(li);
                    }
                else
                    c[i].remove(); // Remove extra categories
            // Add extra categories
            for(var i=cl,l=data.length;i<l;i++){
                li = p.insert(data[i].html).childElements().last();
                li.getStorage()["data"] = data[i];
                assign_category_events(li);
                }
            },
        update_cards_limit=50,
        update_cards = function(data, clean){
            var c=$("js_cards"),
                ta=$A(data).sortBy(function(v){return v.name.toLowerCase()});
            if(clean){
                var thtml="", elms, storage;
                // Stop ellipsis
                stop_ellipsis();
                // Element.update is very slow in IE, so we need to get
                // it done by hand (purge and innerHTML)
                elms = c.childElements();
                if(elms.length > update_cards_limit)
                    // IE has serious performance issues, so we split
                    // tasks and run them at intervals
                    for(var i=0,l=Math.ceil(elms.length/update_cards_limit);i<l;i++)
                        window.setTimeout(
                            (function(elms){
                                return function(){
                                    for(var i=0,l=elms.length;i<l;i++)
                                        elms[i].purge();
                                    };
                                }(elms.slice(i*update_cards_limit, i*update_cards_limit+update_cards_limit))),
                            i*50)
                else
                    for(var i=0,l=elms.length;i<l;i++) elms[i].purge();
                // Update
                for(var i=0,l=ta.length;i<l;i++) thtml += ta[i].html;
                c.innerHTML = thtml;
                // Data and event assign
                elms = c.childElements();
                for(var i=0,l=Math.min(elms.length, ta.length);i<l;i++){
                    elms[i].getStorage()["data"] = ta[i];
                    cardhash[ta[i].path] = elms[i];
                    assign_card_events(elms[i]);
                    }
                // Ellipsis
                multifix_ellipsis(c.select(".text p"));
                }
            else{
                var storage, elm, card, cards, lname;
                for(var k=0,l=ta.length;k<l;k++){
                    elm = null;
                    card = ta[k];
                    if(cardhash[card.path]){ // Card is visible
                        // Update card
                        elm = cardhash[card.path];
                        storage = elm.getStorage()["data"];
                        if(storage.progress!=card.progress){
                            if(card.progress==1){
                                elm.addClassName("finished");
                                elm.removeClassName("unfinished");
                                }
                            else {
                                if(storage.progress==1){
                                    elm.removeClassName("finished");
                                    elm.addClassName("unfinished");
                                    }
                                elm.select(".downloaded")[0].style.width = parseInt(card.progress*100).toString()+"%";
                                }
                            }
                        if(storage.preview!=card.preview)
                            elm.select(".a-image img")[0].src = card.preview;
                        if(storage.name!=card.name){
                            var title = elm.select(".text p")[0];
                            title.update(card.name);
                            fix_ellipsis(title);
                            elm.select(".title")[0].update(card.name);
                            }
                        elm.getStorage()["data"] = card;
                        }
                    else{
                        // Insert card ordered by name
                        lname = card.name.toLowerCase();
                        cards = $H(cardhash).values().sortBy(function(v){
                            return v.getStorage().data.name.toLowerCase();
                            });
                        for(var i=0,j=cards.length;i<j;i++)
                            if(cards[i].getStorage().data.name.toLowerCase() > lname){
                                cards[i].insert({"before": card.html});
                                elm = cards[i].previous();
                                break;
                                    }
                        if(elm===null){
                            // No next element found, append
                            c.insert({"bottom": card.html});
                            elm = c.childElements().last();
                            }
                        elm.getStorage()["data"] = card;
                        assign_card_events(elm);
                        cardhash[card.path] = elm;
                        fix_ellipsis(elm.select(".text p")[0]);
                        }
                    }
                }
            },
        update_undo = function(data){
            var c=$("js_undo");
            if(data)
                c.update(data.html).select("a").on("click", function(){
                    socket.emit("undo", data.id);
                    });
            else
                c.update();
            };
    socket.on("update", function(data){
        var clean = false;
        if(has(data, "path")){
            clean=true;
            update_path(data.path);
            }
        if(has(data, "tasks")) update_tasks(data.tasks, clean);
        if(has(data, "breadcrumbs")) update_breadcrumbs(data.breadcrumbs, clean);
        if(has(data, "categories")) update_categories(data.categories, clean);
        if(has(data, "cards")) update_cards(data.cards, clean);
        if(has(data, "undo")) update_undo(data.undo, clean);
        });
    socket.on("remove", function(data){
        if(has(data, "ids")) remove_cards(data.ids);
        if(has(data, "tasks")) update_tasks(data.tasks);
        });
    // Connection control
    var dom_loaded=false, connected=false,
        updatecon=function(){
            if(dom_loaded&&connected){
                if(path&&path.length) socket.emit("subscribe", "play", path);
                else socket.emit("subscribe", "play");
                }
            },
        addcon=function(){
            connected=true;
            updatecon();
            },
        errorcon=function(){
            window.location.reload();
            },
        domloaded=function(){
            if(!dom_loaded){
                document.observe("click", function(evt){
                    if(reversed_card&&evt.isLeftClick()){
                        var el = evt.element();
                        if((el!=reversed_card)&&(!el.descendantOf(reversed_card))){
                            reversed_card.toggleClassName("reverse", false);
                            reversed_card = null;
                            }
                        }
                    });
                //
                $$(".text p").each(fix_ellipsis);
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
