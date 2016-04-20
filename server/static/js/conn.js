(function(){
    var S4=function(){return (((1+Math.random())*0x10000)|0).toString(16).substring(1);},
        handlers = {},
        encodeUTF8 = function(s){return unescape(encodeURIComponent(s));},
        decodeUTF8 = function(s){return decodeURIComponent(escape(s));},
        add_handler = function(name, callback){
            if(has(handlers, name)) handlers[name][handlers[name].length] = callback
            else handlers[name] = [callback];
            },
        run_handler = function(name, params){
            if(!has(handlers, name)) return null;
            var h = handlers[name];
            for(var i=0,j=h.length;i<j;i++)
                h[i].apply(this, params);
            },
        identifier = (S4() + S4() + "-" + S4() + "-4" + S4().substr(0, 3) + "-" + S4() + "-" + S4() + S4() + S4()).toLowerCase(),
        tasks = [],
        has = function(obj, prop){
            return (typeof obj[prop] != "undefined");
            },
        connected = false,
        timeout = null,
        timeout_relax = 0,
        timeout_relax_threshold = 10,
        timeout_milliseconds = 250,
        increase_timeout = function(){
            if(timeout_relax < timeout_relax_threshold)
                timeout_relax += 1;
            else if(timeout_milliseconds < 1000)
                timeout_milliseconds += 250;
            },
        stress_timeout = function(){
            timeout_relax = 0;
            timeout_milliseconds = 100;
            },
        reset_timeout = function(){
            timeout_relax = timeout_relax_threshold;
            timeout_milliseconds = 250;
            },
        on_ajax_success = function(response){
            var json=response.responseJSON, name;
            if(!json) increase_timeout();
            else if(json.length==0) increase_timeout();
            else{
                reset_timeout();
                try{
                    for(var i=0, l=json.length;i<l;i++){
                        name = json[i].splice(0, 1)[0];
                        if(name=="connect"){
                            if(connected){
                                run_handler("disconnect", json[i]);
                                run_handler("reconnect", json[i]);
                                continue;
                                }
                            connected = true;
                            }
                        run_handler(name, json[i]);
                        }
                    }
                catch(e){
                    if(name!="error") // Do not re-emit error handler errors
                        instance.log(e);
                    }
                }
            },
        on_ajax_failure = function(){
            increase_timeout();
            instance.on("error");
            },
        on_ajax_complete = function(){
            timeout = window.setTimeout(instance.heartbeat, timeout_milliseconds);
            },
        instance = {
            heartbeat: function(){
                if(timeout) window.clearTimeout(timeout);
                var taskscopy = tasks;
                tasks = [];
                new Ajax.Request('/comm', {
                    method: "post",
                    contentType: "text/javascript",
                    postBody: Object.toJSON({"id": identifier, "tasks": taskscopy}),
                    onSuccess: on_ajax_success,
                    onFailure: on_ajax_failure,
                    onComplete: on_ajax_complete
                    });
                },
            emit: function(){
                var a = [];
                for(var i=0, j=arguments.length;i<j;i++)
                    a[a.length] = arguments[i];
                if(a.length>0) tasks[tasks.length] = a;
                stress_timeout();
                instance.heartbeat();
                },
            on: function(name, callback){
                add_handler(name, callback);
                if(connected&&(name=="connect")) callback();
                },
            log: function(e){
                var text=e.toString();
                if(e.name) text += e.name + ": ";
                if(e.message) text += encodeUTF8(e.message); // errors are locale-aware
                else if(e.description) text += encodeUTF8(e.message);
                if(e.number) text += " (code " + e.number.toString() + ")";
                if(e.lineNumber) text += " (line " + e.lineNumber.toString() + ")";
                if(e.stack) text += "\n" + e.stack;
                this.emit("error", text);
                }
            },
        dummy_socketio = {
            connect: function(){
                instance.emit("connect");
                return instance;
                }
            };
    window.io = dummy_socketio;
    window.onerror = function(e){instance.log(e||window.event);};
    }());
